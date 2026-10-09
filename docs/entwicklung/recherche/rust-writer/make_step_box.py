"""Generate a minimal, valid AP214 STEP file of a rectangular box (B-rep).

Box spans x in [-L/2, L/2], y in [-W/2, W/2], z in [z0, z0+H] (mm).
usage: python make_step_box.py out.step L W H [z0] [name]
"""
import sys


def box_step(L, W, H, z0=0.0, name="BOX"):
    a, b = L / 2.0, W / 2.0
    z1 = z0 + H
    ents = []

    def add(s):
        ents.append(s)
        return len(ents)  # 1-based id

    def f(v):
        return f"{v:.6f}".rstrip("0").rstrip(".") + "." if float(v).is_integer() else f"{v:.6f}"

    def pt(x, y, z):
        return add(f"CARTESIAN_POINT('',({f(x)},{f(y)},{f(z)}))")

    def d(x, y, z):
        return add(f"DIRECTION('',({f(x)},{f(y)},{f(z)}))")

    app = add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app})")
    pctx = add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    prod = add(f"PRODUCT('{name}','{name}','',(#{pctx}))")
    pdf = add(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    pdctx = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    pd = add(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdctx})")
    pds = add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#{prod}))")

    len_u = add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    ang_u = add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    sol_u = add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{len_u},'distance_accuracy_value','confusion accuracy')")
    ctx = add(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc})) "
              f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{len_u},#{ang_u},#{sol_u})) "
              f"REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )")

    o = pt(0, 0, 0)
    zd = d(0, 0, 1)
    xd = d(1, 0, 0)
    origin_ax = add(f"AXIS2_PLACEMENT_3D('',#{o},#{zd},#{xd})")

    V = [(-a, -b, z0), (a, -b, z0), (a, b, z0), (-a, b, z0),
         (-a, -b, z1), (a, -b, z1), (a, b, z1), (-a, b, z1)]
    vp = [pt(*p) for p in V]
    vx = [add(f"VERTEX_POINT('',#{p})") for p in vp]
    E = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
    edges = []
    for s, e in E:
        (x1, y1, zz1), (x2, y2, zz2) = V[s], V[e]
        dx, dy, dz = x2 - x1, y2 - y1, zz2 - zz1
        ln = (dx * dx + dy * dy + dz * dz) ** 0.5
        dirn = d(dx / ln, dy / ln, dz / ln)
        vec = add(f"VECTOR('',#{dirn},{f(ln)})")
        line = add(f"LINE('',#{vp[s]},#{vec})")
        edges.append(add(f"EDGE_CURVE('',#{vx[s]},#{vx[e]},#{line},.T.)"))

    # (edge index, same_sense) loops, CCW seen from outside; plane (origin vertex, normal, refdir)
    faces_def = [
        ([(3, False), (2, False), (1, False), (0, False)], 0, (0, 0, -1), (1, 0, 0)),   # bottom
        ([(4, True), (5, True), (6, True), (7, True)], 4, (0, 0, 1), (1, 0, 0)),        # top
        ([(0, True), (9, True), (4, False), (8, False)], 0, (0, -1, 0), (1, 0, 0)),     # front y=-b
        ([(2, True), (11, True), (6, False), (10, False)], 2, (0, 1, 0), (-1, 0, 0)),   # back y=+b
        ([(3, True), (8, True), (7, False), (11, False)], 3, (-1, 0, 0), (0, -1, 0)),   # left x=-a
        ([(1, True), (10, True), (5, False), (9, False)], 1, (1, 0, 0), (0, 1, 0)),     # right x=+a
    ]
    faces = []
    for loop, ov, n, r in faces_def:
        oes = [add(f"ORIENTED_EDGE('',*,*,#{edges[i]},{'.T.' if ss else '.F.'})") for i, ss in loop]
        el = add("EDGE_LOOP('',(" + ",".join(f"#{x}" for x in oes) + "))")
        fb = add(f"FACE_OUTER_BOUND('',#{el},.T.)")
        ax = add(f"AXIS2_PLACEMENT_3D('',#{vp[ov]},#{d(*n)},#{d(*r)})")
        pl = add(f"PLANE('',#{ax})")
        faces.append(add(f"ADVANCED_FACE('',(#{fb}),#{pl},.T.)"))
    shell = add("CLOSED_SHELL('',(" + ",".join(f"#{x}" for x in faces) + "))")
    brep = add(f"MANIFOLD_SOLID_BREP('{name}',#{shell})")
    rep = add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('{name}',(#{origin_ax},#{brep}),#{ctx})")
    add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})")

    # simple grey colour so viewers show something sensible
    rgb = add("COLOUR_RGB('',0.25,0.25,0.25)")
    fill_c = add(f"FILL_AREA_STYLE_COLOUR('',#{rgb})")
    fas = add(f"FILL_AREA_STYLE('',(#{fill_c}))")
    ssfa = add(f"SURFACE_STYLE_FILL_AREA(#{fas})")
    sss = add(f"SURFACE_SIDE_STYLE('',(#{ssfa}))")
    ssu = add(f"SURFACE_STYLE_USAGE(.BOTH.,#{sss})")
    psa = add(f"PRESENTATION_STYLE_ASSIGNMENT((#{ssu}))")
    si = add(f"STYLED_ITEM('color',(#{psa}),#{brep})")
    add(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#{si}),#{ctx})")

    head = ("ISO-10303-21;\nHEADER;\n"
            "FILE_DESCRIPTION(('PartForge generated box'),'2;1');\n"
            f"FILE_NAME('{name}.step','2026-10-07T00:00:00',(''),(''),'partforge-probe','partforge-probe','');\n"
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n")
    body = "".join(f"#{i}={s};\n" for i, s in enumerate(ents, 1))
    return head + body + "ENDSEC;\nEND-ISO-10303-21;\n"


if __name__ == "__main__":
    out, L, W, H = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    z0 = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
    nm = sys.argv[6] if len(sys.argv) > 6 else "BOX"
    with open(out, "w", encoding="ascii", newline="\n") as fh:
        fh.write(box_step(L, W, H, z0, nm))
    print("wrote", out)
