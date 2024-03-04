return {
	"nvimtools/none-ls.nvim",
	config = function()
		local null_ls = require("null-ls")
		null_ls.setup({
			sources = {
				-- lua
				null_ls.builtins.formatting.stylua,
				-- js
				null_ls.builtins.formatting.prettier,
				-- python
				null_ls.builtins.formatting.black,
				null_ls.builtins.formatting.isort,
				null_ls.builtins.diagnostics.pylint.with( {
						-- This has been displaced by running a per-project .nvimrc
						--env = function(params)
						--	return { PYTHONPATH = params.root .. "/src" }
						--end
					}
				),
				-- C / C++
				null_ls.builtins.formatting.clang_format,
			},
		})

		vim.keymap.set("n", "<leader>gf", vim.lsp.buf.format, {})
	end,
}
