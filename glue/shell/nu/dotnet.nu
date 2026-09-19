# .NET: user SDK (~/.dotnet; no-op when native) + global tools.
if ($"($env.HOME)/.dotnet" | path exists) { $env.DOTNET_ROOT = $"($env.HOME)/.dotnet"; cs-prepend $"($env.HOME)/.dotnet" }
cs-append $"($env.HOME)/.dotnet/tools"
