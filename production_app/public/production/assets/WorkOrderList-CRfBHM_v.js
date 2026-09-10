import{h as l,o as f,c,a as k,u as y,b as h,t as m,r as w,d as i}from"./index-D5bNZMgk.js";/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const _=t=>t.replace(/([a-z0-9])([A-Z])/g,"$1-$2").toLowerCase();/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */var a={xmlns:"http://www.w3.org/2000/svg",width:24,height:24,viewBox:"0 0 24 24",fill:"none",stroke:"currentColor","stroke-width":2,"stroke-linecap":"round","stroke-linejoin":"round"};/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const x=({size:t,strokeWidth:e=2,absoluteStrokeWidth:s,color:o,iconNode:n,name:r,class:E,...p},{slots:u})=>l("svg",{...a,width:t||a.width,height:t||a.height,stroke:o||a.stroke,"stroke-width":s?Number(e)*24/Number(t):e,class:["lucide",`lucide-${_(r??"icon")}`],...p},[...n.map(g=>l(...g)),...u.default?[u.default()]:[]]);/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const v=(t,e)=>(s,{slots:o})=>l(x,{...s,iconNode:e,name:t},o);/**
 * @license lucide-vue-next v0.469.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const b=v("FactoryIcon",[["path",{d:"M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z",key:"159hny"}],["path",{d:"M17 18h1",key:"uldtlt"}],["path",{d:"M12 18h1",key:"s9uhes"}],["path",{d:"M7 18h1",key:"1neino"}]]);function L(t){return new URLSearchParams(document.cookie.split("; ").join("&")).get(t)}async function d(t){const e=await t.json();if(!t.ok)throw T(e),new Error((e==null?void 0:e._server_messages)||(e==null?void 0:e.exception)||t.statusText);return e.message}async function S(t,e={},{method:s="GET"}={}){const o=`/api/method/${t}`;if(s==="GET"){const r=new URLSearchParams(e).toString();return d(await fetch(r?`${o}?${r}`:o))}const n=await fetch(o,{method:"POST",headers:{"Content-Type":"application/json","X-Frappe-CSRF-Token":L("csrf_token")||""},body:JSON.stringify(e)});return d(n)}function T(t){console.error("[production_app]",t)}const C={class:"flex min-h-screen flex-col items-center justify-center gap-2 p-8"},$={key:0,class:"text-gray-600"},j={key:1,class:"text-gray-400"},N={__name:"WorkOrderList",setup(t){const e=w("");return f(async()=>{try{e.value=await S("frappe.auth.get_logged_user")}catch{}}),(s,o)=>(i(),c("div",C,[k(y(b),{class:"h-10 w-10 text-gray-500"}),o[0]||(o[0]=h("h1",{class:"text-2xl font-semibold"},"Production App",-1)),e.value?(i(),c("p",$,"Logged in as "+m(e.value),1)):(i(),c("p",j,"Loading session…")),o[1]||(o[1]=h("p",{class:"text-sm text-gray-400"},"Phase 2 placeholder — work order list arrives in Tahap 4.",-1))]))}};export{N as default};
//# sourceMappingURL=WorkOrderList-CRfBHM_v.js.map
