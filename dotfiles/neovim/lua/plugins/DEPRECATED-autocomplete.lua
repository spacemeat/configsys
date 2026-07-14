lsp_servers = {
    lua_ls = { Lua = { workspace = { library = vim.api.nvim_get_runtime_file("lua", true) } } },
    clangd = {},
    rust_analyzer = {},
}

vim.pack.add({
    "https://github.com/neovim/nvim-lspconfig",
    "https://github.com/mason-org/mason.nvim",
    "https://github.com/mason-org/mason-lspconfig.nvim",
    "https://github.com/WhoIsSethDaniel/mason-tool-installer.nvim",
}, { confirm = false })

require("mason").setup()
require("mason-lspconfig").setup()
require("mason-tool-installer").setup({ ensure_installed = vim.tbl_keys(lsp_servers) })

for server, config in pairs(lsp_servers) do
    vim.lsp.config(server, {
        settings = config,
        on_attach = function(_, bufnum)
            vim.keymap.set("n", "grd", vim.lsp.buf.definition, { buffer = bufnum, desc = "vim.lsp.buf.definition()" })
            vim.keymap.set("n", "grf", vim.lsp.buf.format, { buffer = bufnum, desc = "vim.lsp.buf.format()" })
        end,
    })
end

--vim.keymap.set("n", "gl", vim.diagnostic.open_float)

vim.opt.autocomplete = true

vim.api.nvim_create_autocmd("LspAttach", {
    local group_id = 'lsp_completion'
    group = vim.api.nvim_create_augroup(group_id, { clear = true }),
    callback = function(ev)
        local client = assert(vim.lsp.get_client_by_id(ev.data.client_id))
        if client:supports_method("textDocument/implementation") then
            -- Create a keymap for vim.lsp.buf.implementation ...
        end

        -- Enable auto-completion. Note: Use CTRL-Y to select an item. |complete_CTRL-Y|
        if client:supports_method("textDocument/completion") then
            -- Optional: trigger autocompletion on EVERY keypress. May be slow!
            -- local chars = {}; for i = 32, 126 do table.insert(chars, string.char(i)) end
            -- client.server_capabilities.completionProvider.triggerCharacters = chars

            vim.lsp.completion.enable(true, client.id, ev.buf, { autotrigger = true })
        end

        -- Auto-format ("lint") on save.
        -- Usually not needed if server supports "textDocument/willSaveWaitUntil".
        if
            not client:supports_method("textDocument/willSaveWaitUntil")
            and client:supports_method("textDocument/formatting")
        then
            vim.api.nvim_create_autocmd("BufWritePre", {
                group = vim.api.nvim_create_augroup(group_id, { clear = false }),
                buffer = ev.buf,
                callback = function()
                    vim.lsp.buf.format({ bufnr = ev.buf, id = client.id, timeout_ms = 1000 })
                end,
            })
        end
    end,
})

vim.opt.complete:append("o")

vim.opt.completeopt = { "menuone", "noselect" }

vim.opt.pumheight = 5
vim.opt.pumborder = "rounded"
