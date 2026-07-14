vim.pack.add({ "https://github.com/j-hui/fidget.nvim" })
require("fidget").setup({ notification = { override_vim_notify = true } })

vim.pack.add({
    "https://hithub.com/mason-org/mason.nvim",
    "https://github.com/neovim/nvim-lspconfig",
    "https://github.com/mason-org/mason-lspconfig.nvim",
    "https://github.com/mason-tool-installer.nvim",
})

require("mason").setup({})

require("mason-tool-installer").setup({
    ensure_installed = {
        "lua_ls",
        "ts_ls",
        "clangd",
        "rust_analyzer",
        "jsonls",
        "bashls",
        "stylua",
        "prettier",
        "shfmt",
    },
})

vim.lsp.config("lua_ls", {
    settings = {
        Lua = {
            runtime = { version = "LuaJIT" },
            diagnostics = { globals = { "vim" } },
            workspace = {
                checkThirdParty = false,
                library =
                --{ vim.env.VIMRUNTIME, },
                    vim.api.nvim_get_runtime_file("lua", true),
            },
            telemetry = { enable = false },
        },
    },
})

vim.lsp.config("clangd", {})

vim.lsp.config("rust_analyzer", {})

vim.lsp.config("ts_ls", {
    settings = {
        typescript = {
            inlayHints = {
                includeInlayParameterNameHints = "all",
                includeInlayFunctionParameterTypeHints = true,
                includeInlayVariableTypeHints = true,
            },
        },
        javascript = {
            inlayHints = {
                includeInlayParameterNameHints = "all",
                includeInlayFunctionParameterTypeHints = true,
                includeInlayVariableTypeHints = true,
            },
        },
    },
})

require("mason-lspconfig").setup({
    automatic_enable = {
        exclude = { "ts_ls" },
    },
})

vim.lsp.enable("ts_ls")

vim.diagnostic.config({
    severity_sort = true,
    update_in_insert = false,
    float = {
        border = "rounded",
        source = "if_many",
    },
    underline = true,
    virtual_text = {
        spacing = 2,
        source = "if_many",
        prefix = "●",
    },
    signs = {
        text = {
            [vim.diagnostic.severity.ERROR] = "E",
            [vim.diagnostic.severity.WARN] = "W",
            [vim.diagnostic.severity.INFO] = "I",
            [vim.diagnostic.severity.HINT] = "H",
        },
    },
})

vim.opt.autocomplete = true

-- Configure the buffer when an LSP attaches to it.
vim.api.nvim_create_autocmd("LspAttach", {
    group = vim.api.nvim_create_augroup("lsp-attach", { clear = true }),
    callback = function(event)
        vim.keymap.set("n", "<leader>rn", vim.lsp.buf.rename, { buffer = event.buf, desc = "LSP: [R]e[n]ame" })
        vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = event.buf, desc = "LSP: [G]oto [D]efinition" })
        vim.keymap.set("n", "gD", vim.lsp.buf.declaration, { buffer = event.buf, desc = "LSP: [G]oto [D]eclaration" })
        vim.keymap.set(
            "n",
            "gi",
            vim.lsp.buf.implementation,
            { buffer = event.buf, desc = "LSP: [G]oto [I]mplementation" }
        )
        vim.keymap.set("n", "gr", vim.lsp.buf.references, { buffer = event.buf, desc = "LSP: [G]oto [R]eferences" })
        vim.keymap.set(
            { "n", "v" },
            "<leader>ca",
            vim.lsp.buf.code_action,
            { buffer = event.buf, desc = "LSP: [C]ode [A]ction" }
        )
        vim.keymap.set("n", "<leader>f", function()
            vim.lsp.buf.format({ async = true })
        end, { buffer = event.buf, desc = "LSP: [F]ormat" })

        local client = vim.lsp.get_client_by_id(event.data.client_id)

        -- See the substack below for delayed reference highlighting
        -- https://github.com/nvim-lua/kickstart.nvim/blob/master/init.lua

        -- Toggle inlay hints
        if client and client:supports_method("textDocument/inlayHint", event.buf) then
            vim.keymap.set("n", "<leader>th", function()
                vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled)
            end, { buffer = event.buf, desc = "[T]oggle Inlay [H]ints" })
        end

        -- TODO: Autocompletion bits here?
        if client and client:supports_method("textDocument/completion") then
            vim.lsp.completion.enable(true, client.id, event.buf, { autotrigger = true })
        end

        -- auto-format on save
        if
            client
            and not client:supports_method("textDocument/willSaveWaitUntil")
            and client:supports_method("textDocument/formatting")
        then
            vim.api.nvim_create_autocmd("BufWritePre", {
                group = vim.api.nvim_create_augroup("buf-write-pre", { clear = false }),
                buffer = event.buf,
                callback = function()
                    vim.lsp.buf.format({ buffer = event.buf, id = client.id, timeout_ms = 1000 })
                end,
            })
        end
    end,
})

vim.opt.complete:append("o")

vim.opt.completeopt = { "menuone", "noselect", "popup" }

vim.opt.pumheight = 5
vim.opt.pumborder = "rounded"
