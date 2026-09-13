<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import WorkOrderList from './WorkOrderList.vue'
import Workspace from './Workspace.vue'
import { workOrders, loadList, state } from './store.js'
import { ClipboardCheck, Settings, HelpCircle, Factory } from 'lucide-vue-next'

// router hash minimal: '#/' + '#/wo/<id>' (work order), '#/handover' (stock entry)
const hash = ref(window.location.hash)
const onHash = () => {
  hash.value = window.location.hash
  window.scrollTo(0, 0)
}
onMounted(() => {
  window.addEventListener('hashchange', onHash)
  history.scrollRestoration = 'manual'
  window.scrollTo(0, 0)
  // browser memulihkan posisi scroll reload setelah load; paksa kembali ke atas
  setTimeout(() => window.scrollTo(0, 0), 0)
})
onUnmounted(() => window.removeEventListener('hashchange', onHash))

const woId = computed(() =>
  hash.value.startsWith('#/wo/') ? decodeURIComponent(hash.value.slice(5)) : null
)
const section = computed(() => 'workorder')

// drawer ala YouTube: tutup default, burger di top bar membuka/menutup
const navOpen = ref(false)
const activeCount = computed(() => workOrders.filter((w) => w.stage !== 'completed').length)
onMounted(() => { loadList() })

function onNavClick() {
  navOpen.value = false
}
</script>

<template>
  <div class="app" :class="{ 'nav-open': navOpen }">
    <div class="backdrop" :class="{ show: navOpen }" aria-hidden="true" @click="navOpen = false"></div>

    <header class="topbar">
      <button class="navburger" aria-label="Buka/tutup menu" @click="navOpen = !navOpen">
        <span class="bars"><span></span><span></span><span></span></span>
      </button>
      <div class="brand">
        <span class="brandmark"><Factory :size="18" :stroke-width="1.9" /></span>
        <div class="brandtext">
          <span class="brandname">PROD<span class="brandtint">APP</span></span>
          <span class="brandsub">Production workspace</span>
        </div>
      </div>
      <div class="topuser">
        <span class="avatar">AR</span>
        <span class="uinfo">
          <span class="uname">Andi Rahman</span>
          <span class="urole">Production Manager</span>
        </span>
      </div>
    </header>

    <aside class="sidenav" :class="{ open: navOpen }" aria-label="Navigasi utama">
      <div class="sideinner">
        <div class="sidedrop">
          <button class="navburger" aria-label="Tutup menu" @click="navOpen = false">
            <span class="bars"><span></span><span></span><span></span></span>
          </button>
          <div class="brand">
            <span class="brandmark"><Factory :size="18" :stroke-width="1.9" /></span>
            <div class="brandtext">
              <span class="brandname">PROD<span class="brandtint">APP</span></span>
              <span class="brandsub">Production workspace</span>
            </div>
          </div>
        </div>

        <div class="navsection">Workspace</div>
        <a
          href="#/"
          class="navitem"
          :class="{ on: section === 'workorder' }"
          :aria-current="section === 'workorder' ? 'page' : undefined"
          @click="onNavClick"
        >
          <ClipboardCheck :size="18" :stroke-width="1.9" class="nicon" />
          <span class="nlabel">Work Orders</span>
          <span class="navbadge">{{ activeCount }}</span>
        </a>
        <div class="navsection">Sistem</div>
        <span class="navitem disabled" title="Belum tersedia di mockup">
          <Settings :size="18" :stroke-width="1.9" class="nicon" />
          <span class="nlabel">Pengaturan</span>
        </span>
        <span class="navitem disabled" title="Belum tersedia di mockup">
          <HelpCircle :size="18" :stroke-width="1.9" class="nicon" />
          <span class="nlabel">Bantuan</span>
        </span>
      </div>
    </aside>

    <nav class="bottomnav" aria-label="Navigasi utama">
      <a
        href="#/"
        class="bnav-item"
        :class="{ on: section === 'workorder' }"
        :aria-current="section === 'workorder' ? 'page' : undefined"
        @click="onNavClick"
      >
        <span class="bnav-ic">
          <ClipboardCheck :size="20" :stroke-width="1.9" />
          <span v-if="activeCount" class="bnav-badge">{{ activeCount }}</span>
        </span>
        <span class="bnav-label">Work Order</span>
      </a>
    </nav>

    <div class="maincol">
      <div class="content">
        <div v-if="state.error" class="appfoot" style="color:#b3261e">Gagal memuat: {{ state.error }} — <a href="#" @click.prevent="loadList()">coba lagi</a></div>
        <Workspace v-else-if="woId" :key="woId" :id="woId" />
        <WorkOrderList v-else />
        <footer class="appfoot">
          Tersambung ERPNext — server adalah sumber kebenaran.
        </footer>
      </div>
    </div>
  </div>
</template>
