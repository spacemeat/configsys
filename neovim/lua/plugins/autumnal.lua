return {
	{
		"spacemeat/autumnal.nvim",
		dependencies = { "rktjmp/lush.nvim" },
		name = "autumnal",
		branch = "main",
		priority = 1000,
		config = function()
			vim.cmd("colorscheme autumnal")
		end,
	},
}
