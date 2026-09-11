# RESUME — Production App (UI proxy manufacturing ERPNext)

Terakhir diperbarui: 2026-09-11 (setelah Task 24 + deploy UX + push GitHub). File ini = titik mulai sesi baru; baca ini dulu sebelum eksplorasi.

## Status singkat
- App SELESAI & TER-INSTALL di site produksi `posnext.localhost`; suite backend 145/145 ×2, frontend 16/16, review INSTALLATION-READY.
- Task 24 (UX iterasi feedback user) CLOSED: filter range tanggal + cari item/nomor WO, judul kartu = item_NAME, badge & empty-state alur. Deploy live, bundle terverifikasi tersaji.
- Repo ini: GitHub privat Muhayustrid/production-app (main, HEAD 1b53449). `codegraph` ter-index — subagent WAJIB pakai `codegraph_explore` (MCP) dengan projectPath folder app ini sebelum grep/Read; `codegraph sync` setelah commit.

## Topologi akses (PENTING — pernah jadi sumber kebingungan)
- Bench hanya jalan di container docker `erpnext16_dev-frappe-1` (bench: /workspace/development/frappe-bench ↔ host .../ERPNext-Project/development/frappe-bench).
- **URL produksi benar: http://posnext.localhost:8001/production-app** (host 8001 -> container 8000 `bench serve`; ter-pin ke posnext via common_site_config `default_site` + `serve_default_site=true`).
- Port **6788 = site PROOF (sandbox uji)** — JANGAN dipakai melihat data produksi.
- Site: `proof.localhost` (sandbox, tanpa bakery) & `posnext.localhost` (produksi, ada pos_next + bakery_manufacturing — JANGAN diubah/di-uninstall).
- Skrip site: `docker cp <script> erpnext16_dev-frappe-1:/workspace/proofs/` lalu `docker exec -u frappe -w /workspace/development/frappe-bench erpnext16_dev-frappe-1 env/bin/python /workspace/proofs/run_under_site.py <site> <script>`.

## Langkah berikutnya (belum dikerjakan)
1. Assign role **Production Operator / Production Supervisor** ke user nyata di posnext (Administrator).
2. UAT bersama user di posnext.localhost:8001 (filter + alur baru).
3. Keputusan terbuka (spec §16): #3 good=0, #4 kewenangan supervisor-only, #6 scope akses, #7 parity batch bakery, #10 bahan berlebih Stores. (#9 overproduction 25% sudah aktif.)
4. Backlog v2: pagination >100 WO, barcode, timer, dsb.

## Dokumen kunci (ada di repo konteks Muhayustrid/ERPNext-Project, host path ../..//docs & ../..//.superpowers relatif bench)
- Spec final: docs/specs/2026-09-10-production-app-design.md (Revisi 5.1)
- Implementation plan: docs/plans/2026-09-10-production-app-implementation-plan.md
- Ledger SDD lengkap (rulings per task): .superpowers/sdd/production-app-implementation-plan/progress.md
- Runbook install: docs/runbook/production-app-install-id.md
- UAT: docs/uat/production-app-uat-id.md | Bukti proof core: docs/proofs/2026-09-10-core-proof-report.md

## Batasan yang tetap berlaku
- Jangan edit core ERPNext, app `pos_next` (AI lain), `bakery_manufacturing` (akan pensiun).
- Semua transaksi uji di proof.localhost; perubahan setting posnext hati-hati & dilaporkan.
- Password DB tidak pernah ditulis ke file/log/report.
