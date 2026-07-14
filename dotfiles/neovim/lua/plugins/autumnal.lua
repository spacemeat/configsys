vim.pack.add({
    { src = "https://github.com/rktjmp/lush.nvim" }
})

vim.pack.add({
    { src = "https://github.com/spacemeat/autumnal.nvim", requires = "rktjmp/lush.nvim" }
})

vim.cmd("colorscheme autumnal")

