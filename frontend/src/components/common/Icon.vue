<script setup lang="ts">
defineProps<{ name: string }>()
const paths: Record<string, string> = {
 send: 'M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z', layers: 'M12 3 3 8l9 5 9-5-9-5ZM3 13l9 5 9-5M3 18l9 5 9-5',
 database: 'M4 5v14c0 4 16 4 16 0V5M4 5c0-4 16-4 16 0s-16 4-16 0M4 12c0 4 16 4 16 0',
 sliders: 'M4 3v7m0 4v7M12 3v5m0 4v9M20 3v9m0 4v5M2 14h4M10 8h4M18 16h4',
 history: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 7v5l3 2', refresh: 'M20 6v5h-5M4 18v-5h5M6 9A7 7 0 0 1 18 6l2 3M4 15l2 3a7 7 0 0 0 12-3',
 plus: 'M12 5v14M5 12h14', x: 'M18 6 6 18M6 6l12 12', check: 'M20 6 9 17l-5-5', alert: 'M12 3 2.5 20h19L12 3ZM12 10v4M12 17h.01',
 play: 'm7 4 13 8-13 8V4Z', pause: 'M9 5v14M15 5v14', resume: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5', stop: 'M5 5h14v14H5Z',
 edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z', more: 'M5 12h.01M12 12h.01M19 12h.01',
 arrow: 'M5 12h14M13 6l6 6-6 6', up: 'M12 19V5M5 12l7-7 7 7', down: 'M12 5v14M19 12l-7 7-7-7',
 search: 'M16 16l5 5M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0', lock: 'M4 11h16v10H4ZM8 11V7a4 4 0 0 1 8 0v4',
 moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z', sun: 'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1 1M18 18l1 1M5 19l1-1M18 6l1-1',
 folder: 'M3 6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Z', disk: 'M2 5h20v14H2ZM2 14h20M6 9h.01',
 activity: 'M3 12h4l3-8 4 16 3-8h4', terminal: 'M2 4h20v16H2ZM6 9l3 3-3 3M12 15h6', trash: 'M3 6h18M8 6V3h8v3M19 6l-1 15H6L5 6M10 11v5M14 11v5',
 flag: 'M5 21V4M5 4c4-1.5 8 1.5 12 0v11c-4 1.5-8-1.5-12 0', eraser: 'M20 20l-8-8-9 5M16 7l4-4M13 4l7 7', skip: 'm5 4 10 8-10 8V4ZM19 5v14'
}
</script>
<template><span><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path :d="paths[name] || paths.send" /></svg></span></template>
