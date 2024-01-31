return {
	{
		"catppuccin/nvim",
		-- lazy = false,
		name = "catppuccin",
		opts = {
			flavour = "mocha",
			custom_highlights = function(colors)
				return {
					VertSplit = { fg = colors.surface0 },
				}
			end,
			color_overrides = {
				mocha = {
					base = "#0b0500",
					mantle = "#000000",
					crust = "#000000"
				},
			},
		},
		priority = 1000,
		init = function()
			vim.cmd.colorscheme("catppuccin")
		end,
	},
}
