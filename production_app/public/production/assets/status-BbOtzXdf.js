import{c as t}from"./index-Cqo4rrsE.js";/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const i=t("CircleCheckIcon",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m9 12 2 2 4-4",key:"dzmm74"}]]);/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const s=t("CircleDotIcon",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["circle",{cx:"12",cy:"12",r:"1",key:"41hilf"}]]);/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const m=t("PackageIcon",[["path",{d:"M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z",key:"1a0edw"}],["path",{d:"M12 22V12",key:"d0xqtd"}],["path",{d:"m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7",key:"yx3hmr"}],["path",{d:"m7.5 4.27 9 5.15",key:"1c824w"}]]);function l(e){return new Intl.NumberFormat("id-ID",{maximumFractionDigits:3}).format(Number(e)||0)}function d(e){if(!e)return"-";const a=new Date(e);return Number.isNaN(a.getTime())?String(e):a.toLocaleDateString("id-ID",{day:"numeric",month:"short",year:"numeric"})}const r={"Not Started":"Belum Mulai","In Process":"Berjalan",Stopped:"Dihentikan",Closed:"Ditutup",Completed:"Selesai","Stock Reserved":"Reservasi Stok","Stock Partially Reserved":"Reservasi Stok",Cancelled:"Dibatalkan",Submitted:"Disetujui",Draft:"Draft"},c=new Set(["Stopped","Cancelled"]),n=new Set(["Completed","Closed"]);function S(e){return r[e]||e||""}function u(e){return c.has(e)?"bg-amber-100 text-amber-700":n.has(e)?"bg-green-100 text-green-700":"bg-gray-100 text-gray-700"}export{i as C,m as P,d as a,s as b,u as c,l as f,S as w};
