return {
	{
		"williamboman/mason.nvim",
		config = function()
			require("mason").setup()
		end,
	},
	{
		"williamboman/mason-lspconfig.nvim",
		lazy = false,
		opts = {
			auto_install = true,
		},
		--config = function()
		--	require("mason-lspconfig").setup({
		--		ensure_installed = {
		--			"lua_ls",
		--			"tsserver",
		--			"pyright",
		--		},
		--	})
		--end,
	},
	{
		"neovim/nvim-lspconfig",
		config = function()
			local caps = require("cmp_nvim_lsp").default_capabilities()
			local lspconfig = require("lspconfig")
			lspconfig.lua_ls.setup({
				capabilities = caps,
			})
			lspconfig.html.setup({
				capabilities = caps,
			})
			lspconfig.tsserver.setup({
				capabilities = caps,
			})
			lspconfig.pyright.setup({
				capabilities = caps,
			})
			vim.keymap.set("n", "K", vim.lsp.buf.hover, {})
			vim.keymap.set("n", "gd", vim.lsp.buf.definition, {})
			vim.keymap.set("n", "gr", vim.lsp.buf.references, {})
			vim.keymap.set({ "n", "v" }, "<space>ca", vim.lsp.buf.code_action, {})
		end,
	},
}