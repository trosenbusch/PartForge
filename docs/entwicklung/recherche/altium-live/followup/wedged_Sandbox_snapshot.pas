// Isolated DelphiScript sandbox used by the run_altium_script MCP tool.
//
// This is deliberately a SEPARATE script project from Altium_API: a compile
// error or crash in user-supplied script must never break the working MCP
// tooling.
//
// SandboxLog() flushes to disk on every call, so when a script dies silently
// (Altium leaves it paused in the debugger with no dialog) the log still shows
// the last step that completed - the statement after it is the culprit.

const
    REPLACEALL = 1;

var
    LogLines : TStringList;
    LogPath  : String;
    OutPath  : String;
    // Scratch variables: DelphiScript has no inline declarations, so scripts
    // passed to the tool reuse these rather than declaring their own.
    S1, S2, S3 : String;
    I1, I2, I3 : Integer;
    B1         : Integer;
    Obj1, Obj2, Obj3, Obj4, Obj5 : IDispatch;
    List1      : TStringList;
    IntMan     : IIntegratedLibraryManager;
    DbDoc      : IDatabaseLibDocument;

procedure SandboxLog(Msg: String);
begin
    LogLines.Add(Msg);
    LogLines.SaveToFile(LogPath);
end;

procedure Run;
var
    ResultText : String;
    OutLines   : TStringList;
begin
    LogPath := 'C:\Users\Public\altium_mcp\sandbox_log.txt';
    OutPath := 'C:\Users\Public\altium_mcp\sandbox_result.json';
    LogLines := TStringList.Create;
    ResultText := '{"sandbox": "no result set"}';
    SandboxLog('sandbox start');

    try
        // === BEGIN EXPERIMENT (rewritten by the run_altium_script tool) ===
        S1 := 'C:\PartForge-Examples\scratchpad\altium-live\PF_Test_abs.DbLib';
        IntMan := IntegratedLibraryManager;
        IntMan.InstallLibrary(S1);
        SandboxLog('installed');
        DbDoc := IntMan.GetAvailableDBLibDocAtPath(S1);
        If DbDoc = Nil Then Begin SandboxLog('dbdoc nil'); IntMan.UninstallLibrary(S1); Exit; End;
        List1 := TStringList.Create;
        List1.Add('3|RES-0001');
        List1.Add('3|RES-0002');
        For I2 := 0 To List1.Count - 1 Do
        Begin
            I1 := StrToInt(Copy(List1[I2], 1, Pos('|', List1[I2]) - 1));
            S3 := Copy(List1[I2], Pos('|', List1[I2]) + 1, 100);
            S2 := DbDoc.GetTableNameAt(I1);
            SandboxLog('=== ' + S2 + ' / ' + S3);
            SandboxLog('DbDoc.SchLibPath=' + DbDoc.GetSchLibPathForComponent(I1, S3));
            SandboxLog('DbDoc.SchLibRef=' + DbDoc.GetSchLibRefForComponent(I1, S3));
            SandboxLog('DbDoc.Params=' + DbDoc.GetParametersForComponent(I1, S3));
            SandboxLog('IntMan.SchLibPath=' + IntMan.GetSchLibPathForDBComponent(S1, S2, S3));
            SandboxLog('IntMan.SchLibRef=' + IntMan.GetSchLibRefForDBComponent(S1, S2, S3));
            SandboxLog('IntMan.Params=' + IntMan.GetParametersForDBComponent(S1, S2, S3));
            SandboxLog('load comp');
            Obj1 := SchServer.LoadComponentFromDatabaseLibrary(S1, S2, S3);
            If Obj1 = Nil Then SandboxLog('LoadComponentFromDatabaseLibrary -> NIL')
            Else
            Begin
                SandboxLog('COMP LibRef=' + Obj1.LibReference + ' LibraryPath=' + Obj1.LibraryPath + ' SourceLib=' + Obj1.SourceLibraryName + ' DbLib=' + Obj1.DatabaseLibraryName + ' DbTable=' + Obj1.DatabaseTableName + ' DesignItemId=' + Obj1.DesignItemId);
                SandboxLog('COMP Designator=' + Obj1.Designator.Text + ' Comment=' + Obj1.Comment.Text + ' Desc=' + Obj1.ComponentDescription + ' pins=' + IntToStr(Obj1.GetAllPinCount));
                Obj2 := Obj1.SchIterator_Create;
                Obj2.AddFilter_ObjectSet(MkSet(eParameter));
                Obj3 := Obj2.FirstSchObject;
                While Obj3 <> Nil Do
                Begin
                    SandboxLog('  PARAM ' + Obj3.Name + '=' + Obj3.Text + ' hidden=' + BoolToStr(Obj3.IsHidden, True));
                    If Obj3.Name = 'Value' Then
                    Begin
                        ResultText := '';
                        For I3 := 1 To Length(Obj3.Text) Do
                            ResultText := ResultText + IntToStr(Ord(Obj3.Text[I3])) + ' ';
                        SandboxLog('  VALUE codepoints: ' + ResultText);
                    End;
                    Obj3 := Obj2.NextSchObject;
                End;
                Obj1.SchIterator_Destroy(Obj2);
                Obj2 := Obj1.SchIterator_Create;
                Obj2.AddFilter_ObjectSet(MkSet(eImplementation));
                Obj3 := Obj2.FirstSchObject;
                While Obj3 <> Nil Do
                Begin
                    SandboxLog('  IMPL ' + Obj3.ModelName + ' type=' + Obj3.ModelType + ' links=' + IntToStr(Obj3.DatafileLinkCount) + ' current=' + BoolToStr(Obj3.IsCurrent, True) + ' dbModel=' + BoolToStr(Obj3.DatabaseModel, True));
                    Obj3 := Obj2.NextSchObject;
                End;
                Obj1.SchIterator_Destroy(Obj2);
            End;
        End;
        SandboxLog('uninstall');
        IntMan.UninstallLibrary(S1);
        List1.Free;
        ResultText := 'done';
        // === END EXPERIMENT ===
    except
        SandboxLog('EXCEPTION escaped the script body');
        ResultText := '{"error": "exception escaped script - see log for last step"}';
    end;

    SandboxLog('sandbox end');

    OutLines := TStringList.Create;
    try
        OutLines.Text := ResultText;
        OutLines.SaveToFile(OutPath);
    finally
        OutLines.Free;
    end;
end;
