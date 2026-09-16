// ============================================================================
// Orkestrator bulk serah terima (desain bulk-select §4, §7, §8).
// Murni & tanpa dependensi: rpc/loadBoard/onProgress disuntikkan sehingga
// bisa dites node --test tanpa Vue. Adapter RPC aslinya: store.bulkHandoverItem.
// Aturan inti: kartu diproses BERURUTAN (satu transaksi HTTP per kartu),
// gagal bisnis lanjut, gangguan infrastruktur berhenti (uncertain + unprocessed),
// papan dimuat ulang TEPAT SEKALI di akhir.
// ============================================================================

export const BULK_LIMIT = 20

// lane -> action -> flag peran minimal (§3.2). Cold Storage hanya sisi gudang;
// cancel = gudang; verifikasi & kirim = produksi.
export const LANE_ACTIONS = {
  cold: { create_request: ['is_gudang'] },
  request: { cancel_request: ['is_gudang'], save_post_packing: ['is_produksi'] },
  siap: { send_handover: ['is_produksi'] }
}

function refOf(e) {
  return e.work_order || e.material_request
}

// §3.3/§7.1: Box kosong -> null; selain itu angka finiten >= 0.
export function validateBoxKg(value, label = 'Box') {
  if (value === '' || value == null) return null
  const n = Number(value)
  if (!Number.isFinite(n)) throw new Error(`${label} harus angka yang valid.`)
  if (n < 0) throw new Error(`${label} tidak boleh negatif.`)
  return n
}

// §7.1 client envelope: 1–20 ref unik, satu lane, ref non-empty string,
// aksi sesuai lane + peran, Box valid. Mengembalikan entri ternormalisasi.
export function validateBulkEntries(entries, { roles } = {}) {
  if (!Array.isArray(entries)) throw new Error('Pilihan tidak valid.')
  if (entries.length < 1) throw new Error('Pilih minimal 1 kartu.')
  if (entries.length > BULK_LIMIT) throw new Error(`Maksimal ${BULK_LIMIT} kartu per proses massal.`)
  const normalized = entries.map((e, i) => {
    if (!e || typeof e !== 'object') throw new Error('Pilihan tidak valid.')
    const actions = LANE_ACTIONS[e.lane]
    if (!actions) throw new Error('Lane ini tidak mendukung aksi massal.')
    if (!actions[e.action]) throw new Error('Aksi tidak sesuai dengan lane kartu.')
    if (roles && !actions[e.action].some((f) => roles[f])) throw new Error('Aksi tidak tersedia untuk peran Anda.')
    const refKey = e.action === 'create_request' ? 'work_order' : 'material_request'
    if (typeof e[refKey] !== 'string' || !e[refKey].trim()) throw new Error(`Referensi kartu ${i + 1} kosong.`)
    const out = { lane: e.lane, action: e.action, [refKey]: e[refKey] }
    if (e.action === 'save_post_packing') {
      out.box_1 = validateBoxKg(e.box_1, 'Box 1')
      out.box_2 = validateBoxKg(e.box_2, 'Box 2')
    }
    return out
  })
  if (new Set(normalized.map((e) => e.lane)).size > 1) throw new Error('Pilih kartu dari satu lane saja.')
  if (new Set(normalized.map(refOf)).size !== normalized.length) throw new Error('Ada kartu yang dipilih lebih dari sekali.')
  return normalized
}

// §7.3: 'expected' = penolakan bisnis (lanjut); 'transport'/'malformed' =
// infrastruktur (berhenti + uncertain). Kind dipasang oleh store.call().
export function classifyBulkError(error) {
  const kind = error && typeof error === 'object' ? error.bulkKind : null
  if (kind === 'expected' || kind === 'malformed') return kind
  return 'transport' // timeout/network/5xx/kendala tak dikenal -> berhenti (aman)
}

// ============================================================================
// Seleksi & rekonsiliasi (T40 phase B, §2/§3.1/§8) — murni, dites di Node.
// Kartu = objek tampilan HandoverBoard ({ kind, ref, live, pending, ... }).
// Entry pilihan = snapshot datar (tanpa objek kartu) agar tetap sah saat papan
// di-reload di tengah mode pilih.
// ============================================================================

// kind kartu komponen -> lane papan
export const CARD_LANE = { lot: 'cold', request: 'request', siap: 'siap', done: 'kirim' }

// §3.2: aksi massal yang tersedia untuk lane + flag peran sesi
// (dual-role Request Gudang = kedua tombol eksplisit).
export function bulkLaneActions(lane, roles = {}) {
  const actions = LANE_ACTIONS[lane] || {}
  return Object.keys(actions).filter((a) => actions[a].some((f) => roles[f]))
}

// §3.1 eligibility: kartu dirender, lane punya aksi utk peran sesi, live/
// supported/tidak stopped/tidak pending, dan lane cocok dengan kunci pilihan.
export function bulkCardEligible(card, { roles = {}, selectedLane = null } = {}) {
  if (!card || card.pending || !card.live) return false
  const lane = CARD_LANE[card.kind]
  if (!lane || !bulkLaneActions(lane, roles).length) return false
  if (selectedLane && selectedLane !== lane) return false
  return true
}

// snapshot datar satu kartu terpilih (urutan input = urutan proses)
export function bulkEntryOfCard(card) {
  return {
    lane: CARD_LANE[card.kind],
    kind: card.kind,
    ref: card.ref,
    workOrder: card.workOrder || '',
    materialRequest: card.kind === 'lot' ? '' : (card.document || ''),
    name: card.name || '',
    quantity: card.quantity || '',
    batch: card.batch || '',
    note: card.note || ''
  }
}

// §3.1: pilih pertama mengunci lane; kartu ke-21 ditolak dengan pesan jelas;
// kartu yang sama toggle off. Mengembalikan array BARU (urutan terjaga).
export function toggleBulkSelection(selected, entry, limit = BULK_LIMIT) {
  const i = selected.findIndex((e) => e.ref === entry.ref)
  if (i !== -1) {
    const next = selected.slice()
    next.splice(i, 1)
    return next
  }
  if (selected.length && selected[0].lane !== entry.lane) {
    throw new Error('Pilihan terkunci ke satu lane — kosongkan pilihan untuk memilih lane lain.')
  }
  if (selected.length >= limit) {
    throw new Error(`Maksimal ${limit} kartu per proses massal.`)
  }
  return [...selected, entry]
}

// §2: pilih semua = hanya kartu eligible yang dirender di lane terkunci,
// digabung dengan pilihan yang sudah ada, cap 20 dengan penanda truncated.
export function selectAllBulk(cards, { roles = {}, selectedLane = null, selected = [], limit = BULK_LIMIT } = {}) {
  const have = new Set(selected.map((e) => e.ref))
  const entries = selected.slice()
  let truncated = false
  for (const card of cards || []) {
    if (have.has(card.ref) || !bulkCardEligible(card, { roles, selectedLane })) continue
    if (entries.length >= limit) { truncated = true; break }
    entries.push(bulkEntryOfCard(card))
  }
  return { entries, truncated }
}

// §8 rekonsiliasi setelah reload wajib: sukses SELALU dihapus (meski MR yang
// sama muncul lagi di lane berikutnya); gagal/belum diproses/uncertain
// dipertahankan hanya jika masih eligible di lane asal (server truth).
export function reconcileBulkSelection(selected, runResult, isEligible) {
  const cleared = new Set((runResult.successes || []).map((r) => r.ref))
  const retainable = new Set([
    ...(runResult.failures || []),
    ...(runResult.unprocessed || []),
    ...(runResult.uncertain ? [runResult.uncertain] : [])
  ].map((r) => r.ref))
  return selected.filter((e) => !cleared.has(e.ref) && retainable.has(e.ref) && isEligible(e))
}

// §3.4: uncertain/unprocessed tidak boleh dicoba ulang sebelum reload papan
// SELESAI; tanpa kandidat tersisa tidak ada yang bisa dicoba ulang.
export function bulkRetryAvailable(runResult, selectedCount = 0) {
  return !!runResult && runResult.boardReloaded === true && selectedCount > 0
}

// §3.4: run terakhir selesai TANPA reload papan yang sukses — seleksi terlanjur
// dicocokkan dengan papan basi. Semua aksi massal terkunci sampai reload sukses
// atau user keluar mode (yang mengosongkan seleksi).
export function bulkRequiresReload(runResult) {
  return !!runResult && runResult.boardReloaded === false
}

// Refs dari kartu yang SAAT INI DIRENDER dan eligible — kriterianya otomatis
// sama dengan kriteria kartu tampilan (live/supported/stopped/pending/lane+
// peran sudah termuat di array kartu yang dirender). Dipakai untuk rekonsiliasi
// pasca-reload dan validasi pra-run (§7.1 "selected cards are currently
// eligible") sehingga kartu yang tersembunyi filter/halaman tidak diproses.
export function bulkEligibleRefs(cards, roles) {
  const refs = new Set()
  for (const card of cards || []) {
    if (bulkCardEligible(card, { roles })) refs.add(card.ref)
  }
  return refs
}

function entryPayload(e) {
  if (e.action === 'create_request') return { work_order: e.work_order }
  // save_post_packing: kedua box SELALU terkirim (null = kosong).
  if (e.action === 'save_post_packing') {
    return { material_request: e.material_request, box_1: e.box_1 ?? null, box_2: e.box_2 ?? null }
  }
  return { material_request: e.material_request } // cancel_request | send_handover
}

// §4.2: satu request per kartu, berurutan menunggu hasil; gagal 'expected'
// dicatat lalu lanjut; 'transport'/'malformed' -> kartu berjalan 'uncertain',
// sisanya 'unprocessed', run dihentikan. Papan dimuat TEPAT SEKALI di akhir,
// juga saat abort; kegagalan reload tidak membuang hasil yang sudah ada.
export async function runBulkItems(options) {
  const { entries, roles, rpc, loadBoard, onProgress, runId } = options || {}
  if (typeof rpc !== 'function') throw new Error('rpc wajib disediakan.')
  if (!roles || typeof roles !== 'object') throw new Error('roles wajib disediakan.')
  const normalized = validateBulkEntries(entries, { roles })
  const total = normalized.length
  const baseId = runId || `BULK-${Date.now()}`
  const results = []
  let aborted = false

  for (let i = 0; i < total; i++) {
    const e = normalized[i]
    const ref = refOf(e)
    onProgress?.({ done: i, total, ref })
    try {
      await rpc(e.action, entryPayload(e))
      results.push({ ref, action: e.action, status: 'success' })
    } catch (error) {
      if (classifyBulkError(error) === 'expected') {
        results.push({ ref, action: e.action, status: 'failed', message: String(error?.message || 'Aksi ditolak server.') })
      } else {
        // Pesan generik + correlation ID saja — tidak pernah pesan/jejak mentah.
        const correlationId = `${baseId}-${i + 1}`
        results.push({
          ref, action: e.action, status: 'uncertain', correlationId,
          message: `Gangguan koneksi/server saat memproses kartu ini. Kartu mungkin sudah terproses — muat ulang papan untuk memastikan. (Ref: ${correlationId})`
        })
        aborted = true
        break
      }
    }
  }
  for (const e of normalized.slice(results.length)) {
    results.push({ ref: refOf(e), action: e.action, status: 'unprocessed' })
  }

  let boardReloaded = true
  try { await loadBoard?.() } catch { boardReloaded = false }

  return {
    results,
    aborted,
    boardReloaded,
    successes: results.filter((r) => r.status === 'success'),
    failures: results.filter((r) => r.status === 'failed'),
    uncertain: results.find((r) => r.status === 'uncertain') || null,
    unprocessed: results.filter((r) => r.status === 'unprocessed')
  }
}
