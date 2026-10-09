{ PartForge Altium bridge - build a new SchLib from a spec file and save it.

  Uses the verified sequence from altium-live.md section 3.1: new free SCHLIB document,
  SchObjectFactory components/pins/rectangles/parameters/implementations,
  AddSchComponent + SCHM_PrimitiveRegistration, remove the default component,
  SetFileName + DoFileSave(''), close the (unmodified) document.
  Graphic primitives follow altium-mcp's CreateSchematicSymbol (MIT License,
  see THIRD_PARTY_NOTICES.txt). Coordinates in the spec are mils.
  Objects are added in spec order and Altium paints them in that order: the spec
  lists the body graphics before the pins, so a filled body never hides the pin
  names (altium-verify-2 section 3.3; CreateSchematicSymbol also adds the body first).
  The target file must not exist: PartForge writes to a fresh path and replaces the
  real library itself, so Altium never has to overwrite (or prompt).
  TEXTPOS records place the designator and the Comment (mil, TTextJustification);
  PIN fields 13/14 are the inner/outer edge decorations as TIeeeSymbol ordinals 0..6
  (missing fields read as 0 = no symbol). }

procedure PFCmdWriteSchLib(Dummy: Integer);
var
    SpecPath, LibPath, Kind, S, Name, DocFile : String;
    KeepOpen, Ok : Boolean;
    Spec, F : TStringList;
    Doc, SchDoc, DefComp, Comp, LastComp, Obj, Impl : IDispatch;
    I, J, N, Created, SaveResult : Integer;
begin
    SpecPath := PFArg('spec');
    LibPath := PFArg('path');
    KeepOpen := PFArgBool('keep_open');
    Ok := True;
    if not FileExists(SpecPath) then
    begin
        PFFail('spec file not found: ' + SpecPath);
        Ok := False;
    end;
    if Ok then
        if FileExists(LibPath) then
        begin
            PFFail('target file already exists: ' + LibPath);
            Ok := False;
        end;
    if Ok then
        if SchServer = Nil then
        begin
            PFFail('schematic server not available');
            Ok := False;
        end;
    if Ok then
    begin
        Spec := TStringList.Create;
        F := TStringList.Create;
        Spec.LoadFromFile(SpecPath);
        PFLog('spec lines ' + IntToStr(Spec.Count));
        PFLog('create free SCHLIB');
        Doc := CreateNewFreeDocumentFromDocumentKind('SCHLIB', True);
        if Doc = Nil then
        begin
            PFFail('could not create a SchLib document');
            Ok := False;
        end;
        if Ok then
        begin
            SchDoc := SchServer.GetCurrentSchDocument;
            if SchDoc = Nil then
            begin
                PFFail('no current schematic document');
                Ok := False;
            end;
        end;
        if Ok then
            if SchDoc.ObjectID <> 33 then
            begin
                PFFail('current document is not a SchLib');
                Ok := False;
            end;
        if Ok then
        begin
            DocFile := Doc.FileName;
            if Pos(ExtractFileName(DocFile), SchDoc.DocumentName) = 0 then
            begin
                PFFail('current document is not the new SchLib');
                Ok := False;
            end;
        end;
        if Ok then
        begin
            DefComp := SchDoc.CurrentSchComponent;
            Comp := Nil;
            LastComp := Nil;
            Created := 0;
            for I := 0 to Spec.Count - 1 do
            begin
                PFSplit(Spec[I], F);
                Kind := PFField(F, 0);
                if (Kind = 'SYMBOL') or (Kind = 'END') then
                begin
                    if Comp <> Nil then
                    begin
                        SchDoc.AddSchComponent(Comp);
                        SchServer.RobotManager.SendMessage(nil, c_BroadCast, SCHM_PrimitiveRegistration, Comp.I_ObjectAddress);
                        LastComp := Comp;
                        Created := Created + 1;
                        Comp := Nil;
                    end;
                end;
                if Kind = 'SYMBOL' then
                begin
                    Name := PFFieldText(F, 1);
                    PFLog('symbol ' + Name);
                    Comp := SchServer.SchObjectFactory(eSchComponent, eCreate_Default);
                    if Comp = Nil then
                        PFFail('could not create component ' + Name)
                    else
                    begin
                        Comp.CurrentPartID := 1;
                        Comp.DisplayMode := 0;
                        N := PFFieldInt(F, 3);
                        if N < 1 then
                            N := 1;
                        Comp.PartCount := N;
                        Comp.LibReference := Name;
                        Comp.ComponentDescription := PFFieldText(F, 2);
                        Comp.Designator.Text := PFFieldText(F, 4) + '?';
                        S := PFFieldText(F, 5);
                        if S <> '' then
                            Comp.Comment.Text := S;
                        PFOutItem('written', Name);
                    end;
                end
                else if Comp <> Nil then
                begin
                    if Kind = 'PIN' then
                    begin
                        Obj := SchServer.SchObjectFactory(ePin, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Designator := PFFieldText(F, 1);
                            Obj.Name := PFFieldText(F, 2);
                            Obj.Electrical := PFFieldInt(F, 3);
                            Obj.Orientation := PFFieldInt(F, 4);
                            Obj.Location := Point(MilsToCoord(PFFieldInt(F, 5)), MilsToCoord(PFFieldInt(F, 6)));
                            Obj.PinLength := MilsToCoord(PFFieldInt(F, 8));
                            Obj.ShowName := PFFieldBool(F, 9);
                            Obj.ShowDesignator := PFFieldBool(F, 10);
                            Obj.IsHidden := PFFieldBool(F, 11);
                            S := PFFieldText(F, 12);
                            if S <> '' then
                                Obj.Description := S;
                            Obj.Symbol_InnerEdge := PFFieldInt(F, 13);
                            Obj.Symbol_OuterEdge := PFFieldInt(F, 14);
                            Obj.OwnerPartId := PFFieldInt(F, 7);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'TEXTPOS' then
                    begin
                        S := PFField(F, 1);
                        Obj := Nil;
                        if S = 'designator' then
                            Obj := Comp.Designator
                        else if S = 'comment' then
                            Obj := Comp.Comment;
                        if Obj <> Nil then
                        begin
                            Obj.Location := Point(MilsToCoord(PFFieldNum(F, 2)), MilsToCoord(PFFieldNum(F, 3)));
                            Obj.Justification := PFFieldInt(F, 4);
                        end;
                    end
                    else if Kind = 'RECT' then
                    begin
                        Obj := SchServer.SchObjectFactory(eRectangle, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Location := Point(MilsToCoord(PFFieldNum(F, 4)), MilsToCoord(PFFieldNum(F, 5)));
                            Obj.Corner := Point(MilsToCoord(PFFieldNum(F, 6)), MilsToCoord(PFFieldNum(F, 7)));
                            Obj.LineWidth := PFFieldInt(F, 2);
                            Obj.IsSolid := PFFieldBool(F, 3);
                            Obj.Color := PFFieldInt(F, 8);
                            Obj.AreaColor := PFFieldInt(F, 9);
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'ROUNDRECT' then
                    begin
                        Obj := SchServer.SchObjectFactory(eRoundRectangle, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Location := Point(MilsToCoord(PFFieldNum(F, 4)), MilsToCoord(PFFieldNum(F, 5)));
                            Obj.Corner := Point(MilsToCoord(PFFieldNum(F, 6)), MilsToCoord(PFFieldNum(F, 7)));
                            Obj.CornerXRadius := MilsToCoord(PFFieldNum(F, 8));
                            Obj.CornerYRadius := MilsToCoord(PFFieldNum(F, 9));
                            Obj.LineWidth := PFFieldInt(F, 2);
                            Obj.IsSolid := PFFieldBool(F, 3);
                            Obj.Color := PFFieldInt(F, 10);
                            Obj.AreaColor := PFFieldInt(F, 11);
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'LINE' then
                    begin
                        Obj := SchServer.SchObjectFactory(eLine, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Location := Point(MilsToCoord(PFFieldNum(F, 4)), MilsToCoord(PFFieldNum(F, 5)));
                            Obj.Corner := Point(MilsToCoord(PFFieldNum(F, 6)), MilsToCoord(PFFieldNum(F, 7)));
                            Obj.LineWidth := PFFieldInt(F, 2);
                            Obj.Color := PFFieldInt(F, 3);
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'POLYLINE' then
                    begin
                        Obj := SchServer.SchObjectFactory(ePolyline, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            N := PFFieldInt(F, 4);
                            Obj.LineWidth := PFFieldInt(F, 2);
                            Obj.Color := PFFieldInt(F, 3);
                            Obj.VerticesCount := N;
                            for J := 1 to N do
                                Obj.Vertex[J] := Point(MilsToCoord(PFFieldNum(F, 3 + J * 2)), MilsToCoord(PFFieldNum(F, 4 + J * 2)));
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'POLYGON' then
                    begin
                        Obj := SchServer.SchObjectFactory(ePolygon, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            N := PFFieldInt(F, 6);
                            Obj.LineWidth := PFFieldInt(F, 2);
                            Obj.IsSolid := PFFieldBool(F, 3);
                            Obj.Color := PFFieldInt(F, 4);
                            Obj.AreaColor := PFFieldInt(F, 5);
                            Obj.VerticesCount := N;
                            for J := 1 to N do
                                Obj.Vertex[J] := Point(MilsToCoord(PFFieldNum(F, 5 + J * 2)), MilsToCoord(PFFieldNum(F, 6 + J * 2)));
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'ARC' then
                    begin
                        Obj := SchServer.SchObjectFactory(eArc, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Location := Point(MilsToCoord(PFFieldNum(F, 4)), MilsToCoord(PFFieldNum(F, 5)));
                            Obj.Radius := MilsToCoord(PFFieldNum(F, 6));
                            Obj.StartAngle := PFFieldNum(F, 7);
                            Obj.EndAngle := PFFieldNum(F, 8);
                            Obj.LineWidth := PFFieldInt(F, 2);
                            Obj.Color := PFFieldInt(F, 3);
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'ELLIPSE' then
                    begin
                        Obj := SchServer.SchObjectFactory(eEllipse, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Location := Point(MilsToCoord(PFFieldNum(F, 6)), MilsToCoord(PFFieldNum(F, 7)));
                            Obj.Radius := MilsToCoord(PFFieldNum(F, 8));
                            Obj.SecondaryRadius := MilsToCoord(PFFieldNum(F, 9));
                            Obj.LineWidth := PFFieldInt(F, 2);
                            Obj.IsSolid := PFFieldBool(F, 3);
                            Obj.Color := PFFieldInt(F, 4);
                            Obj.AreaColor := PFFieldInt(F, 5);
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'LABEL' then
                    begin
                        Obj := SchServer.SchObjectFactory(eLabel, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Location := Point(MilsToCoord(PFFieldNum(F, 3)), MilsToCoord(PFFieldNum(F, 4)));
                            Obj.Orientation := PFFieldInt(F, 5);
                            Obj.Justification := PFFieldInt(F, 6);
                            Obj.Text := PFFieldText(F, 7);
                            Obj.Color := PFFieldInt(F, 2);
                            Obj.OwnerPartId := PFFieldInt(F, 1);
                            Obj.OwnerPartDisplayMode := 0;
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'PARAM' then
                    begin
                        Obj := SchServer.SchObjectFactory(eParameter, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Name := PFFieldText(F, 1);
                            Obj.Text := PFFieldText(F, 2);
                            Obj.IsHidden := PFFieldBool(F, 3);
                            Obj.Location := Point(MilsToCoord(-50), MilsToCoord(150));
                            Comp.AddSchObject(Obj);
                        end;
                    end
                    else if Kind = 'FPLINK' then
                    begin
                        Impl := Comp.AddSchImplementation;
                        if Impl <> Nil then
                        begin
                            S := PFFieldText(F, 1);
                            Impl.ModelName := S;
                            Impl.ModelType := 'PCBLIB';
                            Impl.Description := PFFieldText(F, 3);
                            Impl.IsCurrent := PFFieldBool(F, 4);
                            Impl.AddDataFileLink(S, PFFieldText(F, 2), 'PCBLIB');
                        end;
                    end;
                end;
            end;
            if Comp <> Nil then
            begin
                SchDoc.AddSchComponent(Comp);
                SchServer.RobotManager.SendMessage(nil, c_BroadCast, SCHM_PrimitiveRegistration, Comp.I_ObjectAddress);
                LastComp := Comp;
                Created := Created + 1;
            end;
            if LastComp <> Nil then
            begin
                if DefComp <> Nil then
                begin
                    PFLog('remove default component');
                    SchDoc.RemoveSchComponent(DefComp);
                end;
                SchDoc.CurrentSchComponent := LastComp;
            end;
            SchDoc.GraphicallyInvalidate;
            PFOutKV('created', IntToStr(Created));
            PFLog('save ' + LibPath);
            S := Doc.SetFileName(LibPath);
            SaveResult := Doc.DoFileSave('');
            PFOutKV('save_result', IntToStr(SaveResult));
            if not FileExists(LibPath) then
                PFFail('library was not saved: ' + LibPath)
            else if not KeepOpen then
            begin
                Doc := Client.GetDocumentByPath(LibPath);
                if Doc <> Nil then
                    if not Doc.Modified then
                    begin
                        PFLog('close ' + LibPath);
                        Client.CloseDocument(Doc);
                        PFOutKV('closed', '1');
                    end;
            end;
        end;
        Spec.Free;
        F.Free;
    end;
end;
