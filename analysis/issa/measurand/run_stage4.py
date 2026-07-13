from __future__ import annotations
import argparse, json, re, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

def norm(s):
    s=str(s).strip().lower()
    s=re.sub(r"[\s\-\./\\]+","_",s)
    return re.sub(r"[^a-z0-9_*]+","",s).strip("_")

def find_col(cols, candidates):
    m={norm(c):str(c) for c in cols}
    for x in candidates:
        if norm(x) in m: return m[norm(x)]
    return None

def to_native(value):
    """Recursively convert NumPy/pandas scalars into JSON/YAML-safe Python types."""
    if isinstance(value, dict):
        return {str(k): to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_native(v) for v in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if np.isnan(value):
            return None
        return float(value)
    if value is pd.NA:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def write(df, base):
    df.to_csv(base.with_suffix(".csv"),index=False)
    try: df.to_parquet(base.with_suffix(".parquet"),index=False)
    except Exception: pass

def subject_key(df, subject, origin):
    s=df[subject].astype("string").str.strip()
    if not origin: return s
    o=df[origin].astype("string").str.strip()
    return o.fillna("<NA>")+"::"+s.fillna("<NA>")

def classify(series, a_tokens, b_tokens):
    def one(v):
        s=str(v).lower()
        if any(t.lower() in s for t in a_tokens): return "A"
        if any(t.lower() in s for t in b_tokens): return "B"
        return pd.NA
    return series.map(one).astype("string")

def pair_delta(df, ita, skey, pair_col, a_tokens, b_tokens, inst_col):
    if not pair_col: return pd.DataFrame(),{"available":False,"pair_count":0}
    cls=classify(df[pair_col].astype("string"),a_tokens,b_tokens)
    w=pd.DataFrame({"subject_key":skey,"class":cls,"ITA":ita})
    w["instrument"]=df[inst_col].astype("string") if inst_col else "<NA>"
    w=w.dropna(subset=["subject_key","class","ITA"])
    if w.empty: return pd.DataFrame(),{"available":False,"pair_count":0}
    p=w.groupby(["subject_key","instrument","class"],dropna=False)["ITA"].mean().unstack("class")
    if "A" not in p or "B" not in p: return pd.DataFrame(),{"available":False,"pair_count":0}
    p=p.dropna(subset=["A","B"]).reset_index()
    p["delta_ITA"]=p["A"]-p["B"]
    return p,{"available":True,"pair_count":len(p),"mean_delta_ita":float(p["delta_ITA"].mean()) if len(p) else None}

def grouped(df, ita, skey, col, min_n):
    if not col: return pd.DataFrame(columns=["group","n","subjects","mean_ita","std_ita"])
    w=pd.DataFrame({"group":df[col].astype("string").fillna("<NA>"),"ITA":ita,"subject_key":skey}).dropna()
    rows=[]
    for g,x in w.groupby("group"):
        if len(x)>=min_n:
            rows.append({"group":str(g),"n":len(x),"subjects":x.subject_key.nunique(),
                         "mean_ita":float(x.ITA.mean()),"std_ita":float(x.ITA.std())})
    return pd.DataFrame(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--canonical-file",type=Path,required=True)
    ap.add_argument("--stage3-summary",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    a=ap.parse_args()
    cfg=yaml.safe_load(Path(__file__).with_name("config.yaml").read_text())
    out=a.output_dir; out.mkdir(parents=True,exist_ok=True)
    s3=json.loads(a.stage3_summary.read_text())
    if s3.get("status")!="CLOSED": raise RuntimeError("Stage 3 is not CLOSED")
    df=pd.read_parquet(a.canonical_file)
    c={k:find_col(df.columns,v) for k,v in cfg["columns"].items()}
    pd.DataFrame([c]).to_csv(out/"resolved_columns.csv",index=False)
    missing=[k for k in ["subject","L","a","b"] if c[k] is None]
    if missing:
        summary={"stage":4,"status":"OPEN_FAILED_GATES","missing_columns":missing,
                 "gates":{"required_columns_resolved":False}}
        (out/"stage4_summary.json").write_text(json.dumps(summary,indent=2))
        (out/"STAGE_4_CLOSED.yaml").write_text(yaml.safe_dump(summary,sort_keys=False))
        print(json.dumps(summary,indent=2)); return 2

    L=pd.to_numeric(df[c["L"]],errors="coerce")
    aa=pd.to_numeric(df[c["a"]],errors="coerce")
    b=pd.to_numeric(df[c["b"]],errors="coerce")
    ita=np.degrees(np.arctan2(L-50.0,b))
    skey=subject_key(df,c["subject"],c["origin"])
    ita_df=pd.DataFrame({"row_index":df.index,"subject_key":skey,"L_star":L,"a_star":aa,
                         "b_star":b,"ITA_reconstructed":ita})
    if c["ita"]:
        ex=pd.to_numeric(df[c["ita"]],errors="coerce")
        ita_df["ITA_existing"]=ex; ita_df["ITA_difference"]=ita-ex
    write(ita_df,out/"ita_values")

    denom=(L-50.0)**2+b**2
    dL=np.degrees(b/np.maximum(denom,1e-12))
    db=np.degrees(-(L-50.0)/np.maximum(denom,1e-12))
    dl=float(cfg["ita"]["delta_L"]); dd=float(cfg["ita"]["delta_b"])
    shifts=np.vstack([
        np.abs(np.degrees(np.arctan2(L+dl-50,b))-ita),
        np.abs(np.degrees(np.arctan2(L-dl-50,b))-ita),
        np.abs(np.degrees(np.arctan2(L-50,b+dd))-ita),
        np.abs(np.degrees(np.arctan2(L-50,b-dd))-ita)])
    sens=pd.DataFrame({"row_index":df.index,"dITA_dL":dL,"dITA_db":db,
        "worst_registered_shift":np.nanmax(shifts,axis=0),
        "b_near_zero":np.abs(b)<=float(cfg["ita"]["b_near_zero"]),
        "b_instability_zone":np.abs(b)<=float(cfg["ita"]["b_instability"])})
    write(sens,out/"ita_numerical_sensitivity")

    work=pd.DataFrame({"ITA":ita,"a_star":aa})
    cov=[]
    for k in ["instrument","body_site","origin","specular"]:
        if c[k]:
            work[k]=df[c[k]].astype("string"); cov.append(k)
    work=work.dropna(subset=["ITA","a_star"])
    X0=pd.get_dummies(work[cov],drop_first=True,dtype=float) if cov else pd.DataFrame(index=work.index)
    y=work.ITA.to_numpy(float)
    pred0=np.repeat(y.mean(),len(y)) if X0.shape[1]==0 else LinearRegression().fit(X0,y).predict(X0)
    X1=X0.copy(); X1["a_star"]=work.a_star.to_numpy(float)
    m1=LinearRegression().fit(X1,y); pred1=m1.predict(X1)
    r20=r2_score(y,pred0); r21=r2_score(y,pred1)
    pr2=(r21-r20)/max(1-r20,1e-12)
    ery=pd.DataFrame([{"rows":len(work),"base_r2":r20,"full_r2":r21,
                       "partial_r2_a_star":pr2,"a_star_coefficient":float(m1.coef_[-1]),
                       "covariates":";".join(cov)}])
    write(ery,out/"erythema_contamination")

    min_n=int(cfg["statistics"]["minimum_group_n"])
    body=grouped(df,ita,skey,c["body_site"],min_n); write(body,out/"body_site_effects")
    inst=grouped(df,ita,skey,c["instrument"],min_n); write(inst,out/"instrument_effects")
    origin=grouped(df,ita,skey,c["origin"],min_n); write(origin,out/"origin_effects")
    spec=grouped(df,ita,skey,c["specular"],min_n); write(spec,out/"specular_group_effects")

    pp,ps=pair_delta(df,ita,skey,c["exposure"],cfg["pairing"]["protected"],cfg["pairing"]["exposed"],c["instrument"])
    write(pp,out/"protected_exposed_pairs")
    sp,ss=pair_delta(df,ita,skey,c["specular"],cfg["pairing"]["sci"],cfg["pairing"]["sce"],c["instrument"])
    write(sp,out/"sci_sce_pairs")

    body_range = (
        float(body.mean_ita.max() - body.mean_ita.min())
        if len(body) >= 2
        else None
    )

    spec_delta = (
        abs(ss.get("mean_delta_ita"))
        if ss.get("mean_delta_ita") is not None
        else None
    )

    instrument_level_count = (
        int(df[c["instrument"]].nunique(dropna=True))
        if c["instrument"] is not None
        else 0
    )

    body_site_level_count = (
        int(df[c["body_site"]].nunique(dropna=True))
        if c["body_site"] is not None
        else 0
    )

    specular_level_count = (
        int(df[c["specular"]].nunique(dropna=True))
        if c["specular"] is not None
        else 0
    )

    exposure_level_count = (
        int(df[c["exposure"]].nunique(dropna=True))
        if c["exposure"] is not None
        else 0
    )

    body_testable = (
        c["body_site"] is not None
        and body_site_level_count >= 2
        and len(body) >= 2
    )

    instrument_testable = (
        c["instrument"] is not None
        and instrument_level_count >= 2
    )

    specular_testable = (
        c["specular"] is not None
        and specular_level_count >= 2
        and ss.get("available", False)
        and ss.get("pair_count", 0) > 0
    )

    exposure_testable = (
        c["exposure"] is not None
        and exposure_level_count >= 2
        and ps.get("available", False)
        and ps.get("pair_count", 0) > 0
    )

    body_restrict = (
        body_testable
        and body_range >= float(
            cfg["statistics"]["site_material_degrees"]
        )
    )

    spec_restrict = (
        specular_testable
        and spec_delta >= float(
            cfg["statistics"]["specular_material_degrees"]
        )
    )

    ery_mat = (
        pr2 >= float(
            cfg["statistics"]["erythema_partial_r2_material"]
        )
    )
    gates = {
        "stage3_closed": True,
        "canonical_row_count_match": (
            len(df)
            == int(cfg["expected"]["canonical_rows"])
        ),
        "required_columns_resolved": not missing,
        "subject_count_reconciled": (
            skey.dropna().nunique()
            == int(cfg["expected"]["subject_ids"])
        ),
        "ita_reconstructed": (
            pd.Series(ita).notna().sum() > 0
        ),
        "ita_numerical_sensitivity_quantified": (
            len(sens) == len(df)
        ),
        "erythema_contamination_quantified": (
            np.isfinite(pr2)
        ),
        "body_site_metadata_resolved": (
            c["body_site"] is not None
        ),
        "body_site_effect_quantified": body_testable,
        "instrument_metadata_resolved": (
            c["instrument"] is not None
        ),
        "specular_metadata_resolved": (
            c["specular"] is not None
        ),
        "protected_pairs_completed_or_optional": (
            ps.get("available")
            or not cfg["closure"]["require_protected_pairs"]
        ),
        "sci_sce_pairs_completed_or_optional": (
            ss.get("available")
            or not cfg["closure"]["require_sci_sce_pairs"]
        ),
    }

    core_closed = all(gates.values())

    unresolved_scope_dimensions = []

    if not instrument_testable:
        unresolved_scope_dimensions.append(
            "instrument_effect_not_estimable_single_level"
        )

    if not specular_testable:
        unresolved_scope_dimensions.append(
            "sci_sce_effect_not_estimable_single_level"
        )

    if not exposure_testable:
        unresolved_scope_dimensions.append(
            "protected_exposed_effect_not_testable"
        )

    status = (
        "CLOSED_WITH_SCOPE_LIMITATION"
        if core_closed and unresolved_scope_dimensions
        else "CLOSED"
        if core_closed
        else "OPEN_FAILED_GATES"
    )
    summary={"stage":4,"name":"measurand_stability_and_biological_nuisance_decomposition",
      "status":status,"canonical_path":str(a.canonical_file),"canonical_sha256":sha(a.canonical_file),
      "canonical_rows":len(df),"resolved_columns":c,"valid_ita_rows":int(pd.Series(ita).notna().sum()),
      "missing_ita_rows":int(pd.Series(ita).isna().sum()),
      "ita_instability_rows":int(sens.b_instability_zone.sum()),
      "ita_p95_registered_perturbation_shift_degrees":float(sens.worst_registered_shift.quantile(.95)),
      "erythema_partial_r2":float(pr2),"erythema_material":bool(ery_mat),
      "instrument_level_count": instrument_level_count,
      "instrument_testable": bool(instrument_testable),
      "body_site_level_count": body_site_level_count,
      "body_site_testable": bool(body_testable),
      "body_site_mean_ita_range": body_range,
      "body_site_restriction_required": (
          bool(body_restrict)
          if body_testable
          else None
      ),
      "specular_level_count": specular_level_count,
      "specular_testable": bool(specular_testable),
      "sci_sce_pair_count": int(
          ss.get("pair_count", 0)
      ),
      "sci_sce_mean_delta_ita": (
          ss.get("mean_delta_ita")
      ),
      "specular_restriction_required": (
          bool(spec_restrict)
          if specular_testable
          else None
      ),
      "exposure_level_count": exposure_level_count,
      "protected_exposed_testable": bool(
          exposure_testable
      ),
      "protected_exposed_pair_count": int(
          ps.get("pair_count", 0)
      ),
      "protected_exposed_mean_delta_ita": (
          ps.get("mean_delta_ita")
      ),
      "unresolved_scope_dimensions": (
          unresolved_scope_dimensions
      ),
      "global_scalar_tone_admissible": (
          False
          if body_restrict or spec_restrict or ery_mat
          else None
          if unresolved_scope_dimensions
          else True
      ),
      "gates":gates,"hard_failed_gates":[k for k,v in gates.items() if not v],
      "next_stage": (
          {
              "id": 5,
              "name": "spectral_geometry_and_effective_information_dimension",
              "inherited_restrictions": [
                  "condition_or_stratify_by_body_location_code",
                  "do_not_claim_cross_instrument_stability",
                  "do_not_claim_SCI_SCE_equivalence",
                  "do_not_claim_protected_exposed_equivalence",
                  "do_not_use_global_subject_skin_tone_scalar",
              ],
          }
          if status in {
              "CLOSED",
              "CLOSED_WITH_SCOPE_LIMITATION",
          }
          else None
      )}
    summary = to_native(summary)

    (out/"stage4_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out/"STAGE_4_CLOSED.yaml").write_text(
        yaml.safe_dump(summary, sort_keys=False),
        encoding="utf-8",
    )
    report=["# ISSA Stage 4 Measurand Stability Report","",f"Status: **{status}**","",
      f"- Valid ITA rows: {summary['valid_ita_rows']}",
      f"- ITA instability rows: {summary['ita_instability_rows']}",
      f"- Erythema partial R²: {summary['erythema_partial_r2']}",
      f"- Body-site mean ITA range: {body_range}",
      f"- SCI/SCE pairs: {summary['sci_sce_pair_count']}",
      f"- Protected/exposed pairs: {summary['protected_exposed_pair_count']}",
      f"- Global scalar tone admissible: {summary['global_scalar_tone_admissible']}","",
      "ITA remains a colorimetric descriptor, not direct melanin concentration."]
    (out/"measurand_report.md").write_text("\n".join(report)+"\n")
    manifest=[]
    for p in sorted(out.iterdir()):
        if p.is_file(): manifest.append({"file":p.name,"sha256":sha(p),"bytes":p.stat().st_size})
    pd.DataFrame(manifest).to_csv(out/"sha256_manifest.csv",index=False)
    print(json.dumps(summary,indent=2,sort_keys=True))
    return (
        0
        if status in {
            "CLOSED",
            "CLOSED_WITH_SCOPE_LIMITATION",
        }
        else 2
    )

if __name__=="__main__": raise SystemExit(main())
