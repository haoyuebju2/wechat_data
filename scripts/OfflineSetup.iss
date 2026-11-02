; Full offline installer. All files are supplied at build time.
#ifndef Payload
  #error Payload directory is required
#endif
#ifndef FileList
  #error Reviewed package file list is required
#endif
#ifndef Output
  #error Output directory is required
#endif
[Setup]
AppId={{5BF23255-6633-440E-A3BA-68600B273BC7}
AppName=微信数据本机工具
AppVersion=0.1.4
AppVerName=微信数据本机工具 0.1.4
AppPublisher=WeChatDataMonitor
DefaultDirName={localappdata}\Programs\WeChatDataMonitor\0.1.4
DefaultGroupName=微信数据本机工具
UsePreviousAppDir=no
UsePreviousTasks=no
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern dynamic
WizardSizePercent=115
Compression=lzma2/fast
SolidCompression=yes
SetupLogging=yes
UninstallDisplayIcon={app}\WeChatDataMonitor.exe
OutputDir={#Output}
OutputBaseFilename=WeChatDataMonitor-0.1.4-Windows-x64-Offline-Setup
CloseApplications=yes
RestartApplications=no

[Languages]
Name: chinesesimp; MessagesFile: compiler:Languages\ChineseSimplified.isl

[Messages]
WelcomeLabel2=本向导将安装完整的微信数据本机工具。%n%n程序、Python 运行环境、依赖库和界面均已包含，安装过程无需联网下载或源码编译。%n%n首次配置本程序的防火墙规则时，Windows 可能要求管理员确认。
FinishedLabel=微信数据本机工具已安装完成。%n%n程序文件与用户数据分开保存；以后卸载程序不会删除位于 AppData 中的聊天缓存和密钥。%n%n单击“完成”退出安装向导。

[Tasks]
Name: desktopicon; Description: 创建桌面快捷方式; GroupDescription: 快捷方式; Flags: checkedonce
Name: autostart; Description: 登录 Windows 后自动启动; GroupDescription: 启动选项; Flags: unchecked

[Files]
#include FileList

[Icons]
Name: {autoprograms}\微信数据本机工具; Filename: {app}\WeChatDataMonitor.exe; WorkingDir: {app}
Name: {autodesktop}\微信数据本机工具; Filename: {app}\WeChatDataMonitor.exe; WorkingDir: {app}; Tasks: desktopicon
Name: {userstartup}\微信数据本机工具; Filename: {app}\WeChatDataMonitor.exe; WorkingDir: {app}; Tasks: autostart

[Run]
Filename: {app}\WeChatDataMonitor.exe; Description: 立即启动微信数据本机工具; Flags: nowait postinstall skipifsilent

[Code]
var
  StageLabel: TNewStaticText;
  ProgressLabel: TNewStaticText;
  DetailsButton: TNewButton;
  DetailsMemo: TNewMemo;
  CurrentStage: String;

procedure ToggleDetails(Sender: TObject);
begin
  DetailsMemo.Visible := not DetailsMemo.Visible;
  if DetailsMemo.Visible then DetailsButton.Caption := '收起详情' else DetailsButton.Caption := '查看详情';
end;

procedure InitializeWizard;
begin
  StageLabel := TNewStaticText.Create(WizardForm);
  StageLabel.Parent := WizardForm.InstallingPage;
  StageLabel.AutoSize := False;
  StageLabel.SetBounds(0, WizardForm.ProgressGauge.Top + ScaleY(30), WizardForm.InstallingPage.Width - ScaleX(80), ScaleY(22));
  StageLabel.Caption := '准备安装完整软件';
  StageLabel.Font.Style := [fsBold];
  ProgressLabel := TNewStaticText.Create(WizardForm);
  ProgressLabel.Parent := WizardForm.InstallingPage;
  ProgressLabel.AutoSize := False;
  ProgressLabel.SetBounds(WizardForm.InstallingPage.Width - ScaleX(75), WizardForm.ProgressGauge.Top + ScaleY(30), ScaleX(75), ScaleY(20));
  ProgressLabel.Alignment := taRightJustify;
  DetailsButton := TNewButton.Create(WizardForm);
  DetailsButton.Parent := WizardForm.InstallingPage;
  DetailsButton.SetBounds(0, WizardForm.ProgressGauge.Top + ScaleY(58), ScaleX(85), ScaleY(25));
  DetailsButton.Caption := '查看详情';
  DetailsButton.OnClick := @ToggleDetails;
  DetailsMemo := TNewMemo.Create(WizardForm);
  DetailsMemo.Parent := WizardForm.InstallingPage;
  DetailsMemo.SetBounds(0, WizardForm.ProgressGauge.Top + ScaleY(92), WizardForm.InstallingPage.Width, ScaleY(75));
  DetailsMemo.ReadOnly := True;
  DetailsMemo.ScrollBars := ssVertical;
  DetailsMemo.Visible := False;
end;

procedure SetStage(Name: String);
begin
  if CurrentStage <> Name then begin
    CurrentStage := Name;
    StageLabel.Caption := Name;
    DetailsMemo.Lines.Add(Name);
  end;
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
var P: Integer;
begin
  if MaxProgress > 0 then P := Round(95.0 * CurProgress / MaxProgress) else P := 0;
  ProgressLabel.Caption := IntToStr(P) + '%';
  WizardForm.ProgressGauge.Max := 100;
  WizardForm.ProgressGauge.Position := P;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var FindRec: TFindRec;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and DirExists(WizardDirValue) then begin
    if FindFirst(AddBackslash(WizardDirValue) + '*', FindRec) then begin
      try
        repeat
          if (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
            MsgBox('请选择新的空目录。现有版本和用户数据不会被覆盖。', mbError, MB_OK);
            Result := False; Break;
          end;
        until not FindNext(FindRec);
      finally FindClose(FindRec); end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Args: String;
begin
  if CurStep = ssInstall then SetStage('校验并安装离线文件');
  if CurStep = ssPostInstall then begin
    SetStage('配置本程序的防火墙规则，请完成 Windows 管理员确认');
    WizardForm.StatusLabel.Caption := '正在完成本机安全配置…';
    WizardForm.FilenameLabel.Caption := '不会修改其他程序的网络权限';
    ProgressLabel.Caption := '95%';
    WizardForm.ProgressGauge.Max := 100;
    WizardForm.ProgressGauge.Position := 95;
    Args := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\resources\policy\Packaged-Firewall.ps1') + '" -Mode Configure';
    if not ShellExec('runas', ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Args, '', SW_HIDE, ewWaitUntilTerminated, Code) then RaiseException('安全配置未完成，安装尚未成功。请检查管理员确认。');
    if Code <> 0 then RaiseException('安全配置未通过，安装尚未成功。应用不会绕过系统隔离启动。');
    SaveStringToFile(ExpandConstant('{app}\installed-version.json'), '{"version":"0.1.4","offline":true,"firewall_ready":true}', False);
    SetStage('安装完成');
    ProgressLabel.Caption := '100%';
    WizardForm.ProgressGauge.Position := 100;
  end;
end;
