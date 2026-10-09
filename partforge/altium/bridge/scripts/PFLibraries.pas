{ PartForge Altium bridge - library management commands.

  ping, installed_libraries, install_library, uninstall_library, open_document,
  document_state, refresh_document, close_own_documents, list_components,
  resolve_db_components, dblib_install_state, refresh_dblib.
  Built only from API calls verified on Altium Designer 26.10 (altium-live.md,
  altium-verify-2 kit); see PFUtils.pas for the coding rules.
  Portions derived from altium-mcp (MIT License) - see THIRD_PARTY_NOTICES.txt. }

procedure PFCmdPing(Dummy: Integer);
var
    V : String;
begin
    V := Client.GetProductVersion;
    PFOutKV('version', V);
    PFOutKV('exchange_dir', PF_EXCHANGE_DIR);
    PFOutKV('sch_server', PFBoolStr(SchServer <> Nil));
    PFOutKV('pcb_server', PFBoolStr(PCBServer <> Nil));
end;

procedure PFCmdInstalledLibraries(Dummy: Integer);
var
    IntMan : IIntegratedLibraryManager;
    I : Integer;
    S : String;
begin
    IntMan := IntegratedLibraryManager;
    if IntMan = Nil then
        PFFail('integrated library manager not available')
    else
    begin
        for I := 0 to IntMan.InstalledLibraryCount - 1 do
        begin
            S := IntMan.InstalledLibraryPath(I);
            PFOutItem('libraries', S);
        end;
        PFOutKV('count', IntToStr(IntMan.InstalledLibraryCount));
    end;
end;

procedure PFCmdInstallLibrary(Dummy: Integer);
var
    IntMan : IIntegratedLibraryManager;
    Path : String;
begin
    Path := PFArg('path');
    IntMan := IntegratedLibraryManager;
    if IntMan = Nil then
        PFFail('integrated library manager not available')
    else if not FileExists(Path) then
        PFFail('library file not found: ' + Path)
    else
    begin
        if PFIsInstalled(Path) then
            PFOutKV('already_installed', '1')
        else
        begin
            PFLog('install ' + Path);
            IntMan.InstallLibrary(Path);
            PFOutKV('already_installed', '0');
        end;
        PFOutKV('installed', PFBoolStr(PFIsInstalled(Path)));
    end;
end;

procedure PFCmdUninstallLibrary(Dummy: Integer);
var
    IntMan : IIntegratedLibraryManager;
    Path : String;
begin
    Path := PFArg('path');
    IntMan := IntegratedLibraryManager;
    if IntMan = Nil then
        PFFail('integrated library manager not available')
    else
    begin
        if PFIsInstalled(Path) then
        begin
            PFLog('uninstall ' + Path);
            IntMan.UninstallLibrary(Path);
            PFOutKV('was_installed', '1');
        end
        else
            PFOutKV('was_installed', '0');
        PFOutKV('installed', PFBoolStr(PFIsInstalled(Path)));
    end;
end;

procedure PFCmdOpenDocument(Dummy: Integer);
var
    Path, Kind : String;
    Doc : IDispatch;
    WasOpen : Boolean;
begin
    Path := PFArg('path');
    Kind := PFArg('kind');
    if not FileExists(Path) then
        PFFail('file not found: ' + Path)
    else
    begin
        WasOpen := Client.IsDocumentOpen(Path);
        if WasOpen then
            Doc := Client.GetDocumentByPath(Path)
        else
        begin
            PFLog('open ' + Path);
            Doc := Client.OpenDocument(Kind, Path);
        end;
        if Doc = Nil then
            PFFail('document could not be opened: ' + Path)
        else
        begin
            Client.ShowDocument(Doc);
            PFOutKV('was_open', PFBoolStr(WasOpen));
        end;
    end;
end;

{ Open/modified state of a document (PartForge refuses to rewrite modified libraries). }
procedure PFCmdDocumentState(Dummy: Integer);
var
    Path : String;
    Doc : IDispatch;
    IsOpen, IsModified : Boolean;
begin
    Path := PFArg('path');
    IsOpen := Client.IsDocumentOpen(Path);
    IsModified := False;
    if IsOpen then
    begin
        Doc := Client.GetDocumentByPath(Path);
        if Doc <> Nil then
            IsModified := Doc.Modified;
    end;
    PFOutKV('open', PFBoolStr(IsOpen));
    PFOutKV('modified', PFBoolStr(IsModified));
end;

{ Show a library rewritten outside Altium: close and reopen it, but only when it is
  unmodified (Altium does not notice outside changes; verified in altium-verify-2).
  A document that was open but not shown (held by Altium itself or by another script)
  is reopened hidden again: PartForge never opens an editor tab the user did not have
  (verified in altium-e2e). }
procedure PFCmdRefreshDocument(Dummy: Integer);
var
    Path, Kind : String;
    Doc : IDispatch;
    WasShown : Boolean;
begin
    Path := PFArg('path');
    Kind := PFArg('kind');
    if not Client.IsDocumentOpen(Path) then
        PFOutKV('state', 'not_open')
    else
    begin
        Doc := Client.GetDocumentByPath(Path);
        if Doc = Nil then
            PFOutKV('state', 'not_open')
        else if Doc.Modified then
            PFOutKV('state', 'modified')
        else
        begin
            WasShown := False;
            if Doc.IsShown then
                WasShown := True;
            PFOutKV('shown', PFBoolStr(WasShown));
            PFLog('close ' + Path);
            Client.CloseDocument(Doc);
            if FileExists(Path) then
            begin
                PFLog('reopen ' + Path);
                Doc := Client.OpenDocument(Kind, Path);
                if Doc <> Nil then
                begin
                    if WasShown then
                        Client.ShowDocument(Doc);
                    PFOutKV('state', 'reloaded');
                end
                else
                    PFFail('document could not be reopened: ' + Path);
            end
            else
                PFOutKV('state', 'closed');
        end;
    end;
end;

{ Close documents PartForge created or opened itself - only when unmodified. }
procedure PFCmdCloseOwnDocuments(Dummy: Integer);
var
    I, Count : Integer;
    Path : String;
    Doc : IDispatch;
begin
    Count := PFArgInt('count');
    for I := 0 to Count - 1 do
    begin
        Path := PFArg('path' + IntToStr(I));
        if Path <> '' then
        begin
            if Client.IsDocumentOpen(Path) then
            begin
                Doc := Client.GetDocumentByPath(Path);
                if Doc <> Nil then
                begin
                    if Doc.Modified then
                        PFOutItem('modified', Path)
                    else
                    begin
                        PFLog('close ' + Path);
                        Client.CloseDocument(Doc);
                        PFOutItem('closed', Path);
                    end;
                end;
            end
            else
                PFOutItem('not_open', Path);
        end;
    end;
end;

procedure PFCmdListComponents(Dummy: Integer);
var
    Path, Kind, S : String;
    WasOpen : Boolean;
    Doc, Lib, It, Comp : IDispatch;
    I, Pins : Integer;
begin
    Path := PFArg('path');
    Kind := UpperCase(PFArg('kind'));
    if not FileExists(Path) then
        PFFail('file not found: ' + Path)
    else
    begin
        WasOpen := Client.IsDocumentOpen(Path);
        if WasOpen then
            Doc := Client.GetDocumentByPath(Path)
        else
        begin
            PFLog('open ' + Path);
            Doc := Client.OpenDocument(Kind, Path);
        end;
        if Doc = Nil then
            PFFail('library could not be opened: ' + Path)
        else
        begin
            if Kind = 'SCHLIB' then
            begin
                Lib := Nil;
                if SchServer <> Nil then
                    Lib := SchServer.GetSchDocumentByPath(Path);
                if Lib = Nil then
                    PFFail('schematic library not available: ' + Path)
                else
                begin
                    It := Lib.SchLibIterator_Create;
                    It.AddFilter_ObjectSet(MkSet(eSchComponent));
                    Comp := It.FirstSchObject;
                    while Comp <> Nil do
                    begin
                        S := Comp.LibReference;
                        Pins := Comp.GetAllPinCount;
                        PFOutLines.Add('ROW|components|' + PFEncode(S) + '|' + IntToStr(Pins));
                        Comp := It.NextSchObject;
                    end;
                    Lib.SchIterator_Destroy(It);
                end;
            end
            else
            begin
                Lib := Nil;
                if PCBServer <> Nil then
                    Lib := PCBServer.GetPCBLibraryByPath(Path);
                if Lib = Nil then
                    PFFail('PCB library not available: ' + Path)
                else
                begin
                    for I := 0 to Lib.ComponentCount - 1 do
                    begin
                        Comp := Lib.GetComponent(I);
                        if Comp <> Nil then
                        begin
                            S := Comp.Name;
                            PFOutLines.Add('ROW|components|' + PFEncode(S) + '|0');
                        end;
                    end;
                end;
            end;
            if not WasOpen then
            begin
                Doc := Client.GetDocumentByPath(Path);
                if Doc <> Nil then
                    if not Doc.Modified then
                    begin
                        PFLog('close ' + Path);
                        Client.CloseDocument(Doc);
                    end;
            end;
        end;
    end;
end;

{ Resolve one database record exactly like Altium does when placing it (helper of
  resolve_db_components; Idx = position of the key in the request). Output rows:
    ROW|res|Idx|loaded|pin_count|symbol_path|symbol_ref|lib_reference|design_item_id|
        description|designator|comment|comment_hidden
    ROW|raw|Idx|<GetParametersForDBComponent>
    ROW|models|Idx|type|name|current        ROW|parameters|Idx|name|value|hidden }
procedure PFResolveOne(DbLib: String; Table: String; Key: String; Idx: String);
var
    IntMan : IIntegratedLibraryManager;
    Path, Ref, S1, S2, Row : String;
    Comp, It, Obj : IDispatch;
    Hidden : Boolean;
begin
    IntMan := IntegratedLibraryManager;
    Path := IntMan.GetSchLibPathForDBComponent(DbLib, Table, Key);
    Ref := IntMan.GetSchLibRefForDBComponent(DbLib, Table, Key);
    S1 := IntMan.GetParametersForDBComponent(DbLib, Table, Key);
    PFOutLines.Add('ROW|raw|' + Idx + '|' + PFEncode(S1));
    Comp := SchServer.LoadComponentFromDatabaseLibrary(DbLib, Table, Key);
    if Comp = Nil then
        PFOutLines.Add('ROW|res|' + Idx + '|0||' + PFEncode(Path) + '|' + PFEncode(Ref) + '||||||')
    else
    begin
        Row := 'ROW|res|' + Idx + '|1|' + IntToStr(Comp.GetAllPinCount) + '|' + PFEncode(Path) + '|' + PFEncode(Ref);
        S1 := Comp.LibReference;
        Row := Row + '|' + PFEncode(S1);
        S1 := Comp.DesignItemId;
        Row := Row + '|' + PFEncode(S1);
        S1 := Comp.ComponentDescription;
        Row := Row + '|' + PFEncode(S1);
        S1 := Comp.Designator.Text;
        Row := Row + '|' + PFEncode(S1);
        Obj := Comp.Comment;
        if Obj = Nil then
            Row := Row + '||'
        else
        begin
            S1 := Obj.Text;
            Hidden := Obj.IsHidden;
            Row := Row + '|' + PFEncode(S1) + '|' + PFBoolStr(Hidden);
        end;
        PFOutLines.Add(Row);
        It := Comp.SchIterator_Create;
        It.AddFilter_ObjectSet(MkSet(eImplementation));
        Obj := It.FirstSchObject;
        while Obj <> Nil do
        begin
            S1 := Obj.ModelType;
            S2 := Obj.ModelName;
            PFOutLines.Add('ROW|models|' + Idx + '|' + PFEncode(S1) + '|' + PFEncode(S2) + '|' + PFBoolStr(Obj.IsCurrent));
            Obj := It.NextSchObject;
        end;
        Comp.SchIterator_Destroy(It);
        It := Comp.SchIterator_Create;
        It.AddFilter_ObjectSet(MkSet(eParameter));
        Obj := It.FirstSchObject;
        while Obj <> Nil do
        begin
            S1 := Obj.Name;
            S2 := Obj.Text;
            PFOutLines.Add('ROW|parameters|' + Idx + '|' + PFEncode(S1) + '|' + PFEncode(S2) + '|' + PFBoolStr(Obj.IsHidden));
            Obj := It.NextSchObject;
        end;
        Comp.SchIterator_Destroy(It);
    end;
end;

{ Resolve many database records in ONE script run (a script start costs about 1.3 s, a
  lookup only milliseconds). Args: dblib, count, table<i>, key<i> for i = 0..count-1;
  rows per key see PFResolveOne, KV count = number of keys resolved.
  A DbLib that is not installed is installed only for the lookups. UninstallLibrary alone
  leaves Altium's hidden DbLib document - and its database connection - open
  (altium-refresh.md 3.3, reproduced in altium-e2e), so that document is closed first
  (only when unmodified, not shown and of kind DATABASELIB). }
procedure PFCmdResolveDbComponents(Dummy: Integer);
var
    IntMan : IIntegratedLibraryManager;
    DbLib, Kind, Idx, Table, Key : String;
    TempInstalled : Boolean;
    I, Count : Integer;
    Doc : IDispatch;
begin
    DbLib := PFArg('dblib');
    Count := PFArgInt('count');
    IntMan := IntegratedLibraryManager;
    if IntMan = Nil then
        PFFail('integrated library manager not available')
    else if not FileExists(DbLib) then
        PFFail('DbLib not found: ' + DbLib)
    else if SchServer = Nil then
        PFFail('schematic server not available')
    else if Count > PF_MAX_RESOLVE then
        PFFail('too many keys: ' + IntToStr(Count))
    else
    begin
        TempInstalled := False;
        if not PFIsInstalled(DbLib) then
        begin
            PFLog('temporary install ' + DbLib);
            IntMan.InstallLibrary(DbLib);
            TempInstalled := True;
        end;
        PFOutKV('temporarily_installed', PFBoolStr(TempInstalled));
        for I := 0 to Count - 1 do
        begin
            Idx := IntToStr(I);
            Table := PFArg('table' + Idx);
            Key := PFArg('key' + Idx);
            PFLog('resolve ' + Idx + ' ' + Table + ' / ' + Key);
            PFResolveOne(DbLib, Table, Key, Idx);
        end;
        PFOutKV('count', IntToStr(Count));
        if TempInstalled then
        begin
            Doc := Client.GetDocumentByPath(DbLib);
            if Doc <> Nil then
                if not Doc.Modified then
                    if not Doc.IsShown then
                    begin
                        Kind := Doc.Kind;
                        if UpperCase(Kind) = 'DATABASELIB' then
                        begin
                            PFLog('close hidden document ' + DbLib);
                            Client.CloseDocument(Doc);
                        end;
                    end;
            if Client.IsDocumentOpen(DbLib) then
                PFOutKV('released', '0')
            else
                PFOutKV('released', '1');
            PFLog('uninstall ' + DbLib);
            IntMan.UninstallLibrary(DbLib);
        end;
    end;
end;

{ DbLib install state: is <path> installed, and which installed libraries share its
  FILE NAME? Placed parts reference a DbLib by file name only; with several installed
  DbLibs of the same name Altium uses the first one (altium-refresh.md 0.5).
  Read-only: nothing is opened, closed, installed or uninstalled. }
procedure PFCmdDbLibInstallState(Dummy: Integer);
var
    IntMan : IIntegratedLibraryManager;
    Path, FileName, S : String;
    I, Position, Matches : Integer;
    Doc : IDispatch;
    IsOpen, IsShown, IsModified : Boolean;
begin
    Path := PFArg('path');
    FileName := PFArg('file_name');
    if FileName = '' then
        FileName := ExtractFileName(Path);
    IntMan := IntegratedLibraryManager;
    if IntMan = Nil then
        PFFail('integrated library manager not available')
    else
    begin
        Position := -1;
        Matches := 0;
        for I := 0 to IntMan.InstalledLibraryCount - 1 do
        begin
            S := IntMan.InstalledLibraryPath(I);
            if UpperCase(S) = UpperCase(Path) then
                if Position < 0 then
                    Position := I;
            if UpperCase(ExtractFileName(S)) = UpperCase(FileName) then
            begin
                Matches := Matches + 1;
                IsOpen := False;
                IsShown := False;
                IsModified := False;
                Doc := Client.GetDocumentByPath(S);
                if Doc <> Nil then
                begin
                    IsOpen := True;
                    if Doc.IsShown then
                        IsShown := True;
                    IsModified := Doc.Modified;
                end;
                PFOutLines.Add('ROW|same_name|' + IntToStr(I) + '|' + PFEncode(S) + '|'
                    + PFBoolStr(UpperCase(S) = UpperCase(Path)) + '|' + PFBoolStr(IsOpen) + '|'
                    + PFBoolStr(IsShown) + '|' + PFBoolStr(IsModified));
            end;
        end;
        PFOutKV('installed', PFBoolStr(Position >= 0));
        PFOutKV('position', IntToStr(Position));
        PFOutKV('same_name_count', IntToStr(Matches));
        PFOutKV('installed_count', IntToStr(IntMan.InstalledLibraryCount));
    end;
end;

{ Make Altium re-read the PartForge database (procedure VERIFIED on Altium 26.10,
  altium-refresh.md 7.4). InstallLibrary, RefreshInstalledLibraries and the Altium
  start load a DbLib as a HIDDEN server document whose ODBC connection pins a SQLite
  snapshot; closing that document makes every later lookup fresh.
  Args: file_name = DbLib FILE NAME (placed parts reference the DbLib by file name),
        rebuild = 1: then run IntegratedLibrary:RefreshInstalledLibraries (clears
        Altium's "not found" cache after inserts; reloads ALL installed libraries,
        about 3 s) and close the reopened document again.
  Only documents of installed libraries with exactly this file name are touched, and
  never one that is shown in an editor or has unsaved edits. }
procedure PFCmdRefreshDbLib(Dummy: Integer);
var
    IntMan : IIntegratedLibraryManager;
    FileName, S, Kind, RowHead : String;
    I, Pass, LastPass, T0, Matches : Integer;
    Refreshed : Boolean;
    Doc : IDispatch;
begin
    FileName := PFArg('file_name');
    LastPass := 0;
    if PFArgBool('rebuild') then
        LastPass := 1;
    IntMan := IntegratedLibraryManager;
    if IntMan = Nil then
        PFFail('integrated library manager not available')
    else if FileName = '' then
        PFFail('dblib file name missing')
    else
    begin
        Matches := 0;
        Refreshed := False;
        for Pass := 0 to LastPass do
        begin
            if Pass = 1 then
            begin
                if Matches > 0 then
                begin
                    PFLog('refresh installed libraries');
                    T0 := GetTickCount;
                    ResetParameters;
                    RunProcess('IntegratedLibrary:RefreshInstalledLibraries');
                    PFOutKV('refresh_ms', IntToStr(GetTickCount - T0));
                    Refreshed := True;
                end;
            end;
            for I := 0 to IntMan.InstalledLibraryCount - 1 do
            begin
                S := IntMan.InstalledLibraryPath(I);
                if UpperCase(ExtractFileName(S)) = UpperCase(FileName) then
                begin
                    if Pass = 0 then
                    begin
                        Matches := Matches + 1;
                        PFOutItem('matched', S);
                    end;
                    RowHead := 'ROW|docs|' + IntToStr(Pass) + '|' + PFEncode(S) + '|';
                    Doc := Client.GetDocumentByPath(S);
                    if Doc = Nil then
                        PFOutLines.Add(RowHead + 'not_open|0')
                    else if Doc.Modified then
                        PFOutLines.Add(RowHead + 'modified|0')
                    else if Doc.IsShown then
                        PFOutLines.Add(RowHead + 'shown|0')
                    else
                    begin
                        Kind := Doc.Kind;
                        if UpperCase(Kind) <> 'DATABASELIB' then
                            PFOutLines.Add(RowHead + 'other_kind|0')
                        else
                        begin
                            PFLog('close hidden document ' + S);
                            T0 := GetTickCount;
                            Client.CloseDocument(Doc);
                            PFOutLines.Add(RowHead + 'closed|' + IntToStr(GetTickCount - T0));
                        end;
                    end;
                end;
            end;
        end;
        PFOutKV('refreshed', PFBoolStr(Refreshed));
        PFOutKV('matched_count', IntToStr(Matches));
    end;
end;
