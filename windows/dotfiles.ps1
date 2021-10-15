function Update-Terminal-Shader
{
	param ($file, $replace, $with)
	((get-content -path $file -raw) -replace $replace,$with) | set-content -path $file
}


$termDir = ("$env:LocalAppData/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState") -replace '\\','/'

if (test-path -path $termDir)
{
	cp terminal/settings.json $termDir/settings.json
	new-item -type directory -force -path $termDir/shaders
	cp -Recurse terminal/*.hlsl $termDir/shaders/
	Update-Terminal-Shader -file $termDir/settings.json -replace "SHADERFILE" -with $termDir/shaders/bearings.hlsl
}