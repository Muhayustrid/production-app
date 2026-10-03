<script setup>
// FU84: halaman "Lainnya" (#/lainnya) — daftar navigasi ke halaman workspace
// yang tidak muat di bottom nav HP (FU84: bottom nav dipangkas ke
// Dashboard/WO/Stock Entry/Form Order + Lainnya). Di PC halaman ini tidak
// ditautkan di sidebar (dua halaman berikut sudah ada di sidebar). Pengaturan
// mengikuti kapabilitas server `can_settings` — pola visibilitas App.vue.
import { computed } from 'vue'
import { ChevronRight, PackageSearch, Settings, Wheat } from 'lucide-vue-next'
import { handoverBoard } from './store.js'

const canSettings = computed(() => !!handoverBoard.roles.can_settings)

const halaman = computed(() => {
  const daftar = [
    {
      href: '#/penggunaan-bahan',
      label: 'Penggunaan bahan baku',
      desc: 'Konsumsi bahan nyata vs rencana BOM, traceability produksi.',
      ico: Wheat,
      tone: 'kgreen'
    },
    {
      href: '#/ketersediaan-stock',
      label: 'Ketersediaan Stock',
      desc: 'Stok, reserved, dan kapasitas produksi di Gudang Produksi.',
      ico: PackageSearch,
      tone: 'kblue'
    }
  ]
  if (canSettings.value) {
    daftar.push({
      href: '#/settings',
      label: 'Pengaturan',
      desc: 'Default gudang Work Order & preferensi tampilan.',
      ico: Settings,
      tone: 'kviolet'
    })
  }
  return daftar
})
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <p class="ph-eye">Navigasi</p>
      <h1>Lainnya</h1>
      <p class="sub">Halaman workspace lainnya di luar menu bawah.</p>
    </div>
  </div>

  <section class="panel ln-card" aria-label="Daftar halaman lainnya">
    <div class="panel-body">
      <nav class="ln-list">
        <a v-for="h in halaman" :key="h.href" class="ln-row" :href="h.href">
          <span class="ln-ico" :class="h.tone" aria-hidden="true">
            <component :is="h.ico" :size="17" :stroke-width="2" />
          </span>
          <span class="ln-text">
            <span class="ln-label">{{ h.label }}</span>
            <span class="ln-desc">{{ h.desc }}</span>
          </span>
          <ChevronRight :size="15" :stroke-width="2" class="mu-chev" aria-hidden="true" />
        </a>
      </nav>
    </div>
  </section>
</template>
