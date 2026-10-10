{ PartForge Altium bridge - entry point.

  Started by PartForge with
    X2.EXE -RScriptingSystem:RunScript(ProjectName="<exchange>\script\PartForgeBridge.PrjScr"|ProcName="PartForgeBridge>Run")
  Reads <exchange>\request.txt, writes a step log (log_<id>.txt, flushed after every
  step) and the response (response_<id>.txt, last line END|<id>).
  Run never shows a dialog and never touches documents it did not create or open.
  Portions derived from altium-mcp (MIT License) - see THIRD_PARTY_NOTICES.txt. }

procedure PFDispatch(Cmd: String);
begin
    if Cmd = 'ping' then
        PFCmdPing(0)
    else if Cmd = 'installed_libraries' then
        PFCmdInstalledLibraries(0)
    else if Cmd = 'install_library' then
        PFCmdInstallLibrary(0)
    else if Cmd = 'uninstall_library' then
        PFCmdUninstallLibrary(0)
    else if Cmd = 'open_document' then
        PFCmdOpenDocument(0)
    else if Cmd = 'document_state' then
        PFCmdDocumentState(0)
    else if Cmd = 'document_states' then
        PFCmdDocumentStates(0)
    else if Cmd = 'refresh_document' then
        PFCmdRefreshDocument(0)
    else if Cmd = 'close_own_documents' then
        PFCmdCloseOwnDocuments(0)
    else if Cmd = 'list_components' then
        PFCmdListComponents(0)
    else if Cmd = 'resolve_db_components' then
        PFCmdResolveDbComponents(0)
    else if Cmd = 'dblib_install_state' then
        PFCmdDbLibInstallState(0)
    else if Cmd = 'refresh_dblib' then
        PFCmdRefreshDbLib(0)
    else if Cmd = 'write_schlib' then
        PFCmdWriteSchLib(0)
    else if Cmd = 'write_pcblib' then
        PFCmdWritePcbLib(0)
    else
        PFFail('unknown command: ' + Cmd);
end;

procedure Run;
var
    ReqPath, Cmd : String;
begin
    PFLogLines := TStringList.Create;
    PFOutLines := TStringList.Create;
    PFRequest := TStringList.Create;
    PFFailed := False;
    PFErrorText := '';
    PFRequestId := 'none';
    PFLogPath := PF_EXCHANGE_DIR + 'log_none.txt';
    ReqPath := PF_EXCHANGE_DIR + 'request.txt';
    if FileExists(ReqPath) then
    begin
        PFRequest.LoadFromFile(ReqPath);
        PFRequestId := PFHeader('ID');
        if not PFValidId(PFRequestId) then
            PFRequestId := 'invalid';
        PFLogPath := PF_EXCHANGE_DIR + 'log_' + PFRequestId + '.txt';
        PFLog('started');
        Cmd := PFHeader('COMMAND');
        PFLog('command ' + Cmd);
        try
            PFDispatch(Cmd);
        except
            PFFail('exception during command ' + Cmd);
        end;
    end
    else
    begin
        PFLog('started without request file');
        PFFail('request file not found');
    end;
    PFWriteResponse(0);
    PFLog('finished');
    PFRequest.Free;
    PFOutLines.Free;
    PFLogLines.Free;
end;
