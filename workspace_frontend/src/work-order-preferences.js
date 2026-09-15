const VIEWS = new Set(['tabel', 'kanban'])

export function normalizeWorkOrderPreferences(values = {}) {
  return {
    q: values.q || '',
    product: values.product || 'all',
    status: values.status || 'all',
    stage: values.stage || 'all',
    from: values.from || '',
    to: values.to || '',
    pageSize: values.pageSize,
    filterOpen: !!values.filterOpen,
    view: VIEWS.has(values.view) ? values.view : 'tabel'
  }
}

export function buildWorkOrderPreferences(values) {
  return normalizeWorkOrderPreferences(values)
}
