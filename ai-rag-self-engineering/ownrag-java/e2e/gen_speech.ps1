# 生成中文语音 wav（Windows SAPI TTS，仅测试用）
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
Write-Output ("voices: " + (($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }) -join ', '))
$zh = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'zh*' } | Select-Object -First 1
if ($zh) { $synth.SelectVoice($zh.VoiceInfo.Name) }
$synth.Rate = -1
$text = "这是一段用于验证音视频解析链路的语音。第一部分，张量是深度学习的基本数据结构，形状决定了信息的组织方式。第二部分，注意力机制让模型学会关注重要的信息。第三部分，残差连接有效缓解了深层网络的梯度消失问题。以上就是全部内容，谢谢观看。"
$synth.SetOutputToWaveFile("$PSScriptRoot\e2e_talk.wav")
$synth.Speak($text)
$synth.SetOutputToNull()
$synth.Dispose()
Write-Output "wav written"
