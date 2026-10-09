{ PartForge Altium bridge - shared helpers (logging, request/response, parsing).

  Part of PartForge. Portions of the bridge design (request/response exchange files,
  spec-file driven library construction, nil-safe server access) are derived from
  altium-mcp (https://github.com/coffeenmusic/altium-mcp), MIT License,
  Copyright (c) 2025 Siddharth Ahuja - see THIRD_PARTY_NOTICES.txt.

  Rules for every unit of this script project (a runtime error pauses the script in the
  debugger and blocks every later script run until the user presses Ctrl+F3):
  * no Exit statements - control flow uses Ok flags,
  * never index a string property of an interface; copy it into a String first,
  * ASCII-only literals; text arrives %uHHHH-escaped and is decoded with Chr,
  * numbers arrive with '.' and are parsed by PFParseNum (never StrToFloat/locale),
  * every interface is checked for Nil before use, Nil checks are not combined,
  * helper procedures take a dummy parameter so only Run appears in Run Script. }

const
    REPLACEALL = 1;
    PF_EXCHANGE_DIR = '@@PF_EXCHANGE_DIR@@';
    PF_SAFE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -_.:\/()+,;=#&@!?*$~^[]<>';
    PF_HEX = '0123456789ABCDEF';
    PF_DIGITS = '0123456789';
    PF_ID_CHARS = '0123456789abcdef';
    PF_MAX_RESOLVE = 200; { keys per resolve_db_components run (PartForge sends at most 50) }

var
    PFLogLines  : TStringList;
    PFLogPath   : String;
    PFOutLines  : TStringList;
    PFRequest   : TStringList;
    PFRequestId : String;
    PFFailed    : Boolean;
    PFErrorText : String;

procedure PFLog(Msg: String);
begin
    PFLogLines.Add(IntToStr(GetTickCount) + ' ' + Msg);
    PFLogLines.SaveToFile(PFLogPath);
end;

procedure PFFail(Msg: String);
begin
    PFFailed := True;
    if PFErrorText = '' then
        PFErrorText := Msg
    else
        PFErrorText := PFErrorText + '; ' + Msg;
    PFLog('ERROR ' + Msg);
end;

function PFBoolStr(Value: Boolean): String;
begin
    if Value then
        Result := '1'
    else
        Result := '0';
end;

function PFHex4(N: Integer): String;
var
    V : Integer;
begin
    V := N;
    if V < 0 then
        V := 0;
    if V > 65535 then
        V := 65535;
    Result := Copy(PF_HEX, ((V div 4096) mod 16) + 1, 1)
        + Copy(PF_HEX, ((V div 256) mod 16) + 1, 1)
        + Copy(PF_HEX, ((V div 16) mod 16) + 1, 1)
        + Copy(PF_HEX, (V mod 16) + 1, 1);
end;

function PFHexValue(H: String): Integer;
var
    I, D, V : Integer;
begin
    V := 0;
    for I := 1 to Length(H) do
    begin
        D := Pos(UpperCase(Copy(H, I, 1)), PF_HEX) - 1;
        if D < 0 then
            D := 0;
        V := V * 16 + D;
    end;
    Result := V;
end;

{ Escape text for the ASCII response file: unsafe characters become %uHHHH. }
function PFEncode(S: String): String;
var
    I : Integer;
    C, R : String;
begin
    R := '';
    for I := 1 to Length(S) do
    begin
        C := Copy(S, I, 1);
        if Pos(C, PF_SAFE) > 0 then
            R := R + C
        else
            R := R + '%u' + PFHex4(Ord(S[I]));
    end;
    Result := R;
end;

{ Decode %uHHHH escapes of a request or spec field. }
function PFDecode(S: String): String;
var
    P : Integer;
    R, Rest : String;
begin
    R := '';
    Rest := S;
    P := Pos('%u', Rest);
    while P > 0 do
    begin
        R := R + Copy(Rest, 1, P - 1) + Chr(PFHexValue(Copy(Rest, P + 2, 4)));
        Rest := Copy(Rest, P + 6, Length(Rest));
        P := Pos('%u', Rest);
    end;
    Result := R + Rest;
end;

{ Locale-independent number parser: optional '-', digits, optional '.' and digits. }
function PFParseNum(S: String): Double;
var
    I, D : Integer;
    V, Scale : Double;
    Neg, InFraction : Boolean;
    T, C : String;
begin
    V := 0;
    Scale := 1;
    Neg := False;
    InFraction := False;
    T := Trim(S);
    for I := 1 to Length(T) do
    begin
        C := Copy(T, I, 1);
        if C = '-' then
            Neg := True
        else if C = '.' then
            InFraction := True
        else
        begin
            D := Pos(C, PF_DIGITS) - 1;
            if D >= 0 then
            begin
                if InFraction then
                begin
                    Scale := Scale / 10;
                    V := V + D * Scale;
                end
                else
                    V := V * 10 + D;
            end;
        end;
    end;
    if Neg then
        V := -V;
    Result := V;
end;

function PFParseInt(S: String): Integer;
begin
    Result := Round(PFParseNum(S));
end;

procedure PFSplit(Line: String; Fields: TStringList);
var
    P : Integer;
    Rest : String;
begin
    Fields.Clear;
    Rest := Line;
    P := Pos('|', Rest);
    while P > 0 do
    begin
        Fields.Add(Copy(Rest, 1, P - 1));
        Rest := Copy(Rest, P + 1, Length(Rest));
        P := Pos('|', Rest);
    end;
    Fields.Add(Rest);
end;

function PFField(Fields: TStringList; Idx: Integer): String;
begin
    Result := '';
    if Idx >= 0 then
        if Idx < Fields.Count then
            Result := Fields[Idx];
end;

function PFFieldText(Fields: TStringList; Idx: Integer): String;
begin
    Result := PFDecode(PFField(Fields, Idx));
end;

function PFFieldNum(Fields: TStringList; Idx: Integer): Double;
begin
    Result := PFParseNum(PFField(Fields, Idx));
end;

function PFFieldInt(Fields: TStringList; Idx: Integer): Integer;
begin
    Result := PFParseInt(PFField(Fields, Idx));
end;

function PFFieldBool(Fields: TStringList; Idx: Integer): Boolean;
begin
    Result := PFField(Fields, Idx) = '1';
end;

{ Value of a request line 'KEY|value' (last occurrence wins). }
function PFHeader(Key: String): String;
var
    I : Integer;
    Line, Prefix : String;
begin
    Result := '';
    Prefix := Key + '|';
    for I := 0 to PFRequest.Count - 1 do
    begin
        Line := PFRequest[I];
        if Pos(Prefix, Line) = 1 then
            Result := Copy(Line, Length(Prefix) + 1, Length(Line));
    end;
end;

function PFArg(Key: String): String;
begin
    Result := PFDecode(PFHeader('ARG|' + Key));
end;

function PFArgInt(Key: String): Integer;
begin
    Result := PFParseInt(PFHeader('ARG|' + Key));
end;

function PFArgBool(Key: String): Boolean;
begin
    Result := PFHeader('ARG|' + Key) = '1';
end;

function PFValidId(S: String): Boolean;
var
    I : Integer;
    Ok : Boolean;
begin
    Ok := Length(S) > 0;
    if Length(S) > 32 then
        Ok := False;
    for I := 1 to Length(S) do
        if Pos(Copy(S, I, 1), PF_ID_CHARS) = 0 then
            Ok := False;
    Result := Ok;
end;

procedure PFOutKV(Key: String; Value: String);
begin
    PFOutLines.Add('KV|' + Key + '|' + PFEncode(Value));
end;

procedure PFOutItem(ListName: String; Value: String);
begin
    PFOutLines.Add('ITEM|' + ListName + '|' + PFEncode(Value));
end;

procedure PFOutWarn(Msg: String);
begin
    PFOutLines.Add('WARN|' + PFEncode(Msg));
    PFLog('WARN ' + Msg);
end;

procedure PFWriteResponse(Dummy: Integer);
var
    Resp : TStringList;
    I : Integer;
begin
    Resp := TStringList.Create;
    Resp.Add('PFRES|1');
    Resp.Add('ID|' + PFRequestId);
    if PFFailed then
    begin
        Resp.Add('STATUS|ERROR');
        Resp.Add('ERROR|' + PFEncode(PFErrorText));
    end
    else
        Resp.Add('STATUS|OK');
    for I := 0 to PFOutLines.Count - 1 do
        Resp.Add(PFOutLines[I]);
    Resp.Add('END|' + PFRequestId);
    Resp.SaveToFile(PF_EXCHANGE_DIR + 'response_' + PFRequestId + '.txt');
    Resp.Free;
end;

{ True if the library path is in Altium's installed libraries (case-insensitive). }
function PFIsInstalled(Path: String): Boolean;
var
    IntMan : IIntegratedLibraryManager;
    I : Integer;
    S : String;
    Found : Boolean;
begin
    Found := False;
    IntMan := IntegratedLibraryManager;
    if IntMan <> Nil then
    begin
        for I := 0 to IntMan.InstalledLibraryCount - 1 do
        begin
            S := IntMan.InstalledLibraryPath(I);
            if UpperCase(S) = UpperCase(Path) then
                Found := True;
        end;
    end;
    Result := Found;
end;
