<script setup>
import { computed, ref, watch } from 'vue'
import { fieldUnits } from './store.js'
import { hasAlternate, parseQtyText, pcsToText, qtyMain } from './format.js'
const props = defineProps({
  label: { type: String, required: true }, unitKey: { type: String, required: true },
  units: { type: Object, required: true }, required: Boolean, disabled: Boolean,
  modelValue: { type: Number, default: null }
})
const emit = defineEmits(['update:modelValue', 'update:valid'])
const unit = computed(() => hasAlternate(props.units) ? (fieldUnits[props.unitKey] || 'pack') : 'pcs')
const text = ref('')
const dirty = ref(false)
const approx = ref(false)
const uid = `qty-${Math.random().toString(36).slice(2)}`
function derive() {
  const value = pcsToText(props.modelValue, unit.value, props.units)
  text.value = value.text
  approx.value = value.approx
  dirty.value = false
}
watch([() => props.modelValue, () => props.units], () => { if (!dirty.value) derive() }, { immediate: true })
watch(unit, derive)
const parsed = computed(() => dirty.value
  ? parseQtyText(text.value, unit.value, props.units)
  : parseQtyText(props.modelValue == null ? '' : String(props.modelValue), 'pcs', props.units))
const valid = computed(() => !parsed.value.error && (!props.required || parsed.value.value != null))
watch(valid, value => emit('update:valid', value), { immediate: true })
function input(event) {
  text.value = event.target.value
  dirty.value = true
  approx.value = false
  const result = parseQtyText(text.value, unit.value, props.units)
  if (!result.error) emit('update:modelValue', result.value)
}
function toggle() { fieldUnits[props.unitKey] = unit.value === 'pack' ? 'pcs' : 'pack' }
</script>
<template>
  <div class="field">
    <label :for="uid">{{ label }} <span v-if="required" class="req">*</span></label>
    <div class="qtywrap" :class="{ invalid: !!parsed.error, disabled }">
      <span v-if="approx" class="approx">≈</span>
      <input :id="uid" :value="text" @input="input" class="qtyinput" inputmode="decimal"
        :disabled="disabled" :aria-invalid="!!parsed.error" />
      <button type="button" class="unitbtn" :disabled="disabled || !hasAlternate(units)" @click="toggle"
        title="Ganti satuan input">{{ unit === 'pack' ? units.displayUom : units.stockUom }}</button>
    </div>
    <div v-if="parsed.error" class="err" role="alert">{{ parsed.error }}</div>
    <div v-else class="hint">{{ qtyMain(parsed.value, units) }}<span v-if="parsed.warn"> · {{ parsed.warn }}</span></div>
  </div>
</template>
