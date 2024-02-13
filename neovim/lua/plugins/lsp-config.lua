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
		opts = {
			servers = {
				clangd = {
					keys = {
						{ "<leader>cR", "<cmd>ClangSwitchSourceHeader<cr>", desc = "Switch Source/Header (C/C++)" },
					},
					root_dir = function(fname)
						return require("lspconfig.util").root_pattern(
							"Makefile", "configure.ac", "configure.in", "config.h.in",
							"meson.build", "meson_options.txt", "build.ninja")(fname)
							  or require("lspconfig.util").root_pattern(
							"compile_commands.json", "compile_flags.txt")(fname)
								or require("lspconfig.util").find_git_ancestor(fname)
					end,
					capabilities = {
						offsetEncoding = { "utf-8" },
					},
					cmd = {
						"clangd", "--background-index", "--clang-tidy", "--header-insertion=iwyu",
						"--completion-style=detailed", "--function-arg-placeholders", "--fallback-style=llvm"
					},
					init_options = {
						usePlaceholders = true,
						completeUnimported = true,
						clangFileStatus = true,
					},
				},
			},
			setup = {
				clangd = function(_, opts)
					local clangd_ext_opts = require("lazyvim.util").opts("clangd_extensions.nvim")
					require("clangd-extensions").setup(vim.tbl_deep_extend(
						"force", clangd_ext_opts or {}, { server = opts }))
				end,
			},
		},
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
			lspconfig.clangd.setup({
				capabilities = caps,
			})
			vim.keymap.set("n", "K", vim.lsp.buf.hover, {})
			vim.keymap.set("n", "gd", vim.lsp.buf.definition, {})
			vim.keymap.set("n", "gr", vim.lsp.buf.references, {})
			vim.keymap.set("n", "rn", vim.lsp.buf.rename, {})
			vim.keymap.set({ "n", "v" }, "<space>ca", vim.lsp.buf.code_action, {})
		end,
	},
}
