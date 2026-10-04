# Prebuilt libraries

Drop prebuilt `*.lib` files here — every `*.lib` in this folder is linked as-is
(SDCC manual §3.2.4). Both projects list this folder as `"../shared/lib"` in the
`libraries` array of their `sdcc-project.json`; remove that entry or add more
folders to scan.
