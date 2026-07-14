vim.pack.add({
    "http://github.com/nvim-lua/plenary.nvim",
    "http://github.com/nvim-tree/nvim-web-devicons",
    "http://github.com/nvim-telescope/telescope.nvim",
    "http://github.com/nvim-telescope/telescope-ui-select.nvim",
    "http://github.com/nvim-telescope/telescope-fzf-native.nvim",
}, { confirm = false })

require("telescope").setup({
    extensions = { ["ui-select"] = { require("telescope.themes").get_dropdown() } },
})

pcall(require("telescope").load_extension, "fzf")
pcall(require("telescope").load_extension, "ui-select")

local pickers = require("telescope.builtin")

vim.keymap.set("n", "<leader>sp", pickers.builtin, { desc = "[S]earch Builtin [P]ickers" })
vim.keymap.set("n", "<leader>sk", pickers.keymaps, { desc = "[S]earch [K]eymaps" })
vim.keymap.set("n", "<leader>sb", pickers.buffers, { desc = "[S]earch [B]uffers" })
vim.keymap.set("n", "<leader>sf", pickers.find_files, { desc = "[S]earch [F]iles" })
vim.keymap.set({ "n", "v" }, "<leader>sw", pickers.grep_string, { desc = "[S]earch Current [W]ord" })
vim.keymap.set("n", "<leader>sg", pickers.live_grep, { desc = "[S]earch by [G]rep" })
vim.keymap.set("n", "<leader>sr", pickers.resume, { desc = "[S]earch [R]esume" })
vim.keymap.set("n", "<leader>sc", pickers.commands, { desc = "[S]earch [C]commands" })

vim.keymap.set("n", "<leader>sh", pickers.help_tags, { desc = "[S]earch [H]elp" })
vim.keymap.set("n", "<leader>sm", pickers.man_pages, { desc = "[S]earch [M]anuals" })

vim.keymap.set("n", "<leader>/", function()
    pickers.current_buffer_fuzzy_find(require("telescope.themes").get_dropdown({
        winblend = 10,
        previewer = false,
    }))
end, { desc = "[/] Fuzzily search in current buffer" })

vim.keymap.set("n", "<leader>sn", function()
    pickers.find_files({ cwd = vim.fn.stdpath("config") })
end, { desc = "[S]earch [N]eovim files" })
