vim.pack.add({ { src = "https://github.com/nvim-treesitter/nvim-treesitter", version = "main" } }, { confirm = false })

local parsers = {
    "bash",
    "c",
    "diff",
    "html",
    "javascript",
    "lua",
    "luadoc",
    "markdown",
    "markdown_inline",
    "query",
    "rust",
    "vim",
    "vimdoc",
    "zig",
}

require("nvim-treesitter").setup({ auto_install = true })
require("nvim-treesitter").install(parsers)
