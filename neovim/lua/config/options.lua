-- vim.cmd("set tabstop=4")
-- vim.cmd("set softtabstop=4")
-- vim.cmd("set shiftwidth=4")

vim.opt.termguicolors = true

vim.opt.number = true
vim.opt.relativenumber = true

vim.opt.tabstop = 4
vim.opt.softtabstop = 4
vim.opt.shiftwidth = 4

vim.opt.cursorline = true
vim.opt.cursorlineopt = "number"

vim.o.encoding = "utf-8"

-- This runs a .nvimrc file in a project root if it exists.
-- I did this to get pylint to know about packages not findable
-- from the project root.
if vim.fn.filereadable('.nvimrc') == 1 then
	vim.api.nvim_command('source .nvimrc')
end
