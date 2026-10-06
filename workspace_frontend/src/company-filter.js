// FU95: opsi <select> filter company global — SATU bentuk di semua halaman
// (label "Semua company" selalu pertama). allValue = sentinel halaman:
// native <select> memakai '' (artinya tanpa scope), PrimeVue Select memakai
// 'ALL' (string kosong dianggap "tidak ada pilihan" — gotcha FU73).
export function companySelectOptions(companies, allValue = '') {
  return [
    { label: 'Semua company', value: allValue },
    ...(companies || []).map((c) => ({ label: c, value: c }))
  ]
}

// perusahaan terlihat user lebih dari satu → pemilih company ditampilkan
// (satu company: filter tak bermakna, UI disembunyikan — konvensi FU73)
export function showCompanyPicker(companies) {
  return (companies || []).length > 1
}
