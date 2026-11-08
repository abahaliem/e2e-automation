// Tema bersama mockup QA Agent (terang). Nama token tetap, nilainya dipetakan ke palet terang:
// ink-950 = latar halaman, ink-900 = permukaan kartu/panel, ink-700 = garis, fg = teks.
tailwind.config = {
  theme: {
    extend: {
      fontFamily: { sans: ['Geist', 'system-ui', 'sans-serif'], mono: ['"Geist Mono"', 'monospace'] },
      colors: {
        ink: {
          950: '#f3f4f7', // latar halaman
          900: '#fdfdfe', // permukaan
          850: '#f7f8fa', // permukaan sekunder
          800: '#edf0f5', // item aktif / hover
          700: '#e1e4ea', // garis
          600: '#cdd2db', // garis tegas
          500: '#9aa0ab',
        },
        fg: { DEFAULT: '#15171c', muted: '#585d69', dim: '#858a96' },
        accent: { DEFAULT: '#2560e8', soft: 'rgba(37,96,232,0.07)', line: 'rgba(37,96,232,0.45)' },
        pass: '#1b8f5b', fail: '#cf3b36', review: '#a8760f',
      },
    },
  },
};
