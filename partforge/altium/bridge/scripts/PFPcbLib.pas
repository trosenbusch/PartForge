{ PartForge Altium bridge - build a new PcbLib from a spec file and save it.

  Uses the verified sequence from altium-live.md section 3.2: new free PCBLIB document,
  CreatePCBLibComp + RegisterComponent, pads/tracks via PCBObjectFactory, extruded
  component bodies via PCBContourFactory + ModelFactory_CreateExtruded,
  SetFileName + DoFileSave(''), removal of the default footprint, close.
  Arcs, regions and texts follow altium-mcp's CreateFootprintsBatch (MIT License,
  see THIRD_PARTY_NOTICES.txt). Coordinates in the spec are millimetres; layers are
  'L<TLayer>' or 'M<mechanical number>'. Not supported: STEP embedding, mask/paste
  overrides (PartForge reports these as warnings). }

{ Layer token -> TLayer: 'L74' = Multi-Layer, 'M15' = ILayer.MechanicalLayer(15). }
function PFLayer(Token: String): Integer;
var
    Kind : String;
    N : Integer;
begin
    Result := 0;
    Kind := Copy(Token, 1, 1);
    N := PFParseInt(Copy(Token, 2, Length(Token)));
    if Kind = 'M' then
    begin
        if N >= 1 then
            if N <= 32 then
                Result := ILayer.MechanicalLayer(N);
    end
    else if Kind = 'L' then
        Result := N;
end;

procedure PFCmdWritePcbLib(Dummy: Integer);
var
    SpecPath, LibPath, Kind, S, Name, DefName, DocFile, BoardFile : String;
    KeepOpen, Ok, DefIsOurs : Boolean;
    Spec, F, Names : TStringList;
    Doc, PcbLib, Comp, FirstComp, DefComp, Obj, Contour, Model : IDispatch;
    I, J, N, Created, Shape, HoleType, Layer, SaveResult : Integer;
    Hole : Double;
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
        if PCBServer = Nil then
        begin
            PFFail('PCB server not available');
            Ok := False;
        end;
    if Ok then
    begin
        Spec := TStringList.Create;
        F := TStringList.Create;
        Names := TStringList.Create;
        Spec.LoadFromFile(SpecPath);
        PFLog('spec lines ' + IntToStr(Spec.Count));
        PFLog('create free PCBLIB');
        Doc := CreateNewFreeDocumentFromDocumentKind('PCBLIB', True);
        if Doc = Nil then
        begin
            PFFail('could not create a PcbLib document');
            Ok := False;
        end;
        if Ok then
        begin
            PcbLib := PCBServer.GetCurrentPCBLibrary;
            if PcbLib = Nil then
            begin
                PFFail('no current PCB library');
                Ok := False;
            end;
        end;
        if Ok then
        begin
            DocFile := Doc.FileName;
            BoardFile := PcbLib.Board.FileName;
            if Pos(ExtractFileName(DocFile), BoardFile) = 0 then
            begin
                PFFail('current PCB library is not the new document');
                Ok := False;
            end;
        end;
        if Ok then
        begin
            DefName := '';
            DefComp := PcbLib.CurrentComponent;
            if DefComp <> Nil then
                DefName := DefComp.Name;
            Comp := Nil;
            FirstComp := Nil;
            Created := 0;
            PCBServer.PreProcess;
            for I := 0 to Spec.Count - 1 do
            begin
                PFSplit(Spec[I], F);
                Kind := PFField(F, 0);
                if (Kind = 'FOOTPRINT') or (Kind = 'END') then
                begin
                    if Comp <> Nil then
                    begin
                        PCBServer.SendMessageToRobots(PcbLib.Board.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Comp.I_ObjectAddress);
                        Created := Created + 1;
                        Comp := Nil;
                    end;
                end;
                if Kind = 'FOOTPRINT' then
                begin
                    Name := PFFieldText(F, 1);
                    PFLog('footprint ' + Name);
                    Comp := PCBServer.CreatePCBLibComp;
                    if Comp = Nil then
                        PFFail('could not create footprint ' + Name)
                    else
                    begin
                        Comp.Name := Name;
                        Comp.Description := PFFieldText(F, 2);
                        Comp.Height := MMsToCoord(PFFieldNum(F, 3));
                        PcbLib.RegisterComponent(Comp);
                        if FirstComp = Nil then
                            FirstComp := Comp;
                        Names.Add(Name);
                        PFOutItem('written', Name);
                    end;
                end
                else if Comp <> Nil then
                begin
                    if Kind = 'PAD' then
                    begin
                        Obj := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.Name := PFFieldText(F, 1);
                            Obj.Mode := ePadMode_Simple;
                            Obj.x := MMsToCoord(PFFieldNum(F, 2));
                            Obj.y := MMsToCoord(PFFieldNum(F, 3));
                            Layer := PFLayer(PFField(F, 5));
                            Obj.Layer := Layer;
                            Hole := PFFieldNum(F, 10);
                            if Hole > 0 then
                            begin
                                Obj.HoleSize := MMsToCoord(Hole);
                                HoleType := PFFieldInt(F, 11);
                                Obj.HoleType := HoleType;
                                if HoleType = 2 then
                                begin
                                    Obj.HoleWidth := MMsToCoord(PFFieldNum(F, 12));
                                    Obj.HoleRotation := PFFieldNum(F, 13);
                                end;
                                Obj.Plated := PFFieldBool(F, 14);
                            end
                            else
                                Obj.HoleSize := 0;
                            Obj.TopXSize := MMsToCoord(PFFieldNum(F, 7));
                            Obj.TopYSize := MMsToCoord(PFFieldNum(F, 8));
                            Shape := PFFieldInt(F, 6);
                            Obj.TopShape := Shape;
                            if Shape = 9 then
                            begin
                                Obj.StackCRPctOnLayer[eTopLayer] := PFFieldInt(F, 9);
                                Obj.StackCRPctOnLayer[eBottomLayer] := PFFieldInt(F, 9);
                            end;
                            Obj.Rotation := PFFieldNum(F, 4);
                            Comp.AddPCBObject(Obj);
                            PCBServer.SendMessageToRobots(Comp.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj.I_ObjectAddress);
                        end;
                    end
                    else if Kind = 'TRACK' then
                    begin
                        Obj := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.x1 := MMsToCoord(PFFieldNum(F, 3));
                            Obj.y1 := MMsToCoord(PFFieldNum(F, 4));
                            Obj.x2 := MMsToCoord(PFFieldNum(F, 5));
                            Obj.y2 := MMsToCoord(PFFieldNum(F, 6));
                            Obj.Width := MMsToCoord(PFFieldNum(F, 2));
                            Layer := PFLayer(PFField(F, 1));
                            Obj.Layer := Layer;
                            Comp.AddPCBObject(Obj);
                            PCBServer.SendMessageToRobots(Comp.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj.I_ObjectAddress);
                        end;
                    end
                    else if Kind = 'ARC' then
                    begin
                        Obj := PCBServer.PCBObjectFactory(eArcObject, eNoDimension, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.XCenter := MMsToCoord(PFFieldNum(F, 3));
                            Obj.YCenter := MMsToCoord(PFFieldNum(F, 4));
                            Obj.Radius := MMsToCoord(PFFieldNum(F, 5));
                            Obj.StartAngle := PFFieldNum(F, 6);
                            Obj.EndAngle := PFFieldNum(F, 7);
                            Obj.LineWidth := MMsToCoord(PFFieldNum(F, 2));
                            Layer := PFLayer(PFField(F, 1));
                            Obj.Layer := Layer;
                            Comp.AddPCBObject(Obj);
                            PCBServer.SendMessageToRobots(Comp.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj.I_ObjectAddress);
                        end;
                    end
                    else if Kind = 'REGION' then
                    begin
                        Obj := PCBServer.PCBObjectFactory(eRegionObject, eNoDimension, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Contour := PCBServer.PCBContourFactory;
                            N := PFFieldInt(F, 2);
                            for J := 1 to N do
                                Contour.AddPoint(MMsToCoord(PFFieldNum(F, 1 + J * 2)), MMsToCoord(PFFieldNum(F, 2 + J * 2)));
                            Obj.SetOutlineContour(Contour);
                            Layer := PFLayer(PFField(F, 1));
                            Obj.Layer := Layer;
                            Obj.Kind := 0;
                            Comp.AddPCBObject(Obj);
                            PCBServer.SendMessageToRobots(Comp.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj.I_ObjectAddress);
                        end;
                    end
                    else if Kind = 'TEXT' then
                    begin
                        Obj := PCBServer.PCBObjectFactory(eTextObject, eNoDimension, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Obj.XLocation := MMsToCoord(PFFieldNum(F, 2));
                            Obj.YLocation := MMsToCoord(PFFieldNum(F, 3));
                            Obj.Size := MMsToCoord(PFFieldNum(F, 4));
                            Obj.Width := MMsToCoord(PFFieldNum(F, 5));
                            Layer := PFLayer(PFField(F, 1));
                            Obj.Layer := Layer;
                            Obj.UseTTFonts := False;
                            Obj.Text := PFFieldText(F, 7);
                            Obj.Rotation := PFFieldNum(F, 6);
                            Comp.AddPCBObject(Obj);
                            PCBServer.SendMessageToRobots(Comp.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj.I_ObjectAddress);
                        end;
                    end
                    else if Kind = 'BODY' then
                    begin
                        Obj := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
                        if Obj <> Nil then
                        begin
                            Contour := PCBServer.PCBContourFactory;
                            N := PFFieldInt(F, 6);
                            for J := 1 to N do
                                Contour.AddPoint(MMsToCoord(PFFieldNum(F, 5 + J * 2)), MMsToCoord(PFFieldNum(F, 6 + J * 2)));
                            Obj.SetOutlineContour(Contour);
                            Layer := PFLayer(PFField(F, 1));
                            Obj.Layer := Layer;
                            Obj.BodyProjection := eBoardSide_Top;
                            Obj.BodyColor3D := PFFieldInt(F, 4);
                            Obj.BodyOpacity3D := PFFieldNum(F, 5);
                            Model := Obj.ModelFactory_CreateExtruded(MMsToCoord(PFFieldNum(F, 2)), MMsToCoord(PFFieldNum(F, 3)), PFFieldInt(F, 4));
                            Obj.Model := Model;
                            Comp.AddPCBObject(Obj);
                            PCBServer.SendMessageToRobots(Comp.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj.I_ObjectAddress);
                        end;
                    end;
                end;
            end;
            if Comp <> Nil then
            begin
                PCBServer.SendMessageToRobots(PcbLib.Board.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Comp.I_ObjectAddress);
                Created := Created + 1;
            end;
            PCBServer.PostProcess;
            PFOutKV('created', IntToStr(Created));
            PFLog('save ' + LibPath);
            S := Doc.SetFileName(LibPath);
            SaveResult := Doc.DoFileSave('');
            PFOutKV('save_result', IntToStr(SaveResult));
            DefIsOurs := False;
            for I := 0 to Names.Count - 1 do
                if Names[I] = DefName then
                    DefIsOurs := True;
            if DefName <> '' then
                if not DefIsOurs then
                    if FirstComp <> Nil then
                    begin
                        DefComp := PcbLib.GetComponentByName(DefName);
                        if DefComp <> Nil then
                        begin
                            PFLog('remove default footprint ' + DefName);
                            PcbLib.CurrentComponent := FirstComp;
                            PcbLib.RemoveComponent(DefComp);
                            Doc.Modified := True;
                            SaveResult := Doc.DoFileSave('');
                            PFOutKV('save_result_2', IntToStr(SaveResult));
                        end;
                    end;
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
        Names.Free;
    end;
end;
