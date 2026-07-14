from __future__ import annotations
import argparse, hashlib, json, math, re
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from sklearn.decomposition import PCA

def norm_name(v):
    v=re.sub(r"[\s\-\./\\]+","_",str(v).strip().lower())
    return re.sub(r"[^a-z0-9_*]+","",v).strip("_")

def find_col(cols,candidates):
    m={norm_name(c):str(c) for c in cols}
    for c in candidates:
        if norm_name(c) in m:return m[norm_name(c)]
    return None

def sha256_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def native(v):
    if isinstance(v,dict):return {str(k):native(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [native(x) for x in v]
    if isinstance(v,np.bool_):return bool(v)
    if isinstance(v,np.integer):return int(v)
    if isinstance(v,np.floating):return None if np.isnan(v) else float(v)
    if v is pd.NA:return None
    if isinstance(v,float) and math.isnan(v):return None
    return v

def write_table(df,base):
    df.to_csv(base.with_suffix('.csv'),index=False)
    try:df.to_parquet(base.with_suffix('.parquet'),index=False)
    except Exception:pass

def resolve_wavelengths(df,cfg):
    e=cfg['expected']; p=cfg['reflectance']['prefix']
    expected=list(range(int(e['wavelength_start_nm']),int(e['wavelength_end_nm'])+int(e['wavelength_step_nm']),int(e['wavelength_step_nm'])))
    resolved=[(w,f'{p}{w}') for w in expected if f'{p}{w}' in df.columns]
    missing=[w for w in expected if f'{p}{w}' not in df.columns]
    return expected,resolved,missing

def normalize(X,cfg):
    a=X.to_numpy(float); finite=a[np.isfinite(a)]
    if finite.size==0:raise RuntimeError('No finite reflectance values')
    raw_max=float(finite.max()); mode=str(cfg['reflectance']['scale']).lower()
    scale=('percent' if raw_max>float(cfg['reflectance']['percent_detection_threshold']) else 'fraction') if mode=='auto' else mode
    factor=0.01 if scale=='percent' else 1.0
    Y=X.astype(float)*factor
    return Y,{'source_scale':scale,'normalization_factor':factor,'raw_min':float(finite.min()),'raw_median':float(np.median(finite)),'raw_max':raw_max,'normalized_min':float(np.nanmin(Y)),'normalized_median':float(np.nanmedian(Y)),'normalized_max':float(np.nanmax(Y))}

def descriptors(X,wavelengths,floor):
    a=np.asarray(X,float); wl=np.asarray(wavelengths,float)
    idx={w:wavelengths.index(w) for w in [450,500,540,560,580,600,650,700]}
    safe=lambda x:np.clip(x,floor,None)
    slope=np.polyfit(wl,a.T,1)[0]
    q=(wl-wl.mean())**2; q=q-q.mean()
    curv=((a-a.mean(1,keepdims=True))@q)/np.sum(q*q)
    r={w:a[:,i] for w,i in idx.items()}
    return pd.DataFrame({
      'broadband_mean_reflectance':a.mean(1),
      'linear_slope_per_nm':slope,
      'quadratic_curvature':curv,
      'red_green_contrast_650_560':r[650]-r[560],
      'blue_red_contrast_450_650':r[450]-r[650],
      'log_red_green_ratio_650_560':np.log(safe(r[650]))-np.log(safe(r[560])),
      'hemoglobin_proxy_540_580_vs_600':0.5*(r[540]+r[580])-r[600],
      'hemoglobin_log_proxy':0.5*(np.log(safe(r[540]))+np.log(safe(r[580])))-np.log(safe(r[600])),
      'visible_span_700_450':r[700]-r[450],
      'green_band_depth_560_vs_500_650':r[560]-0.5*(r[500]+r[650]),
    })

def align(ref,cand):
    out=cand.copy(); signs=[]
    for i in range(ref.shape[0]):
        s=1.0 if float(np.dot(ref[i],cand[i]))>=0 else -1.0
        out[i]*=s; signs.append(int(s))
    return out,signs

def cosine(a,b):
    d=np.linalg.norm(a)*np.linalg.norm(b)
    return float(np.dot(a,b)/d) if d>0 else np.nan

def mass_interval(load,wavelengths,fraction):
    z=np.abs(np.asarray(load,float)); total=float(z.sum())
    if total<=0:return None,None,None
    order=np.argsort(z)[::-1]; chosen=[]; cum=0.0
    for i in order:
        chosen.append(i);cum+=z[i]
        if cum/total>=fraction:break
    ws=sorted(wavelengths[i] for i in chosen)
    return int(min(ws)),int(max(ws)),float(cum/total)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--canonical-file',type=Path,required=True);ap.add_argument('--stage6-summary',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);args=ap.parse_args()
    cfg=yaml.safe_load(Path(__file__).with_name('config.yaml').read_text())
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    s6=json.loads(args.stage6_summary.read_text())
    allowed=set(cfg['closure']['admissible_stage6_status'])
    if s6.get('status') not in allowed:raise RuntimeError('Stage 6 status not admissible')
    if cfg['closure']['require_site_specific_basis'] and s6.get('preferred_representation')!='site_specific_basis':raise RuntimeError('Site-specific basis not inherited')
    if s6.get('registered_compact_component_count')!=int(cfg['closure']['require_compact_components']):raise RuntimeError('Compact dimension mismatch')
    df=pd.read_parquet(args.canonical_file)
    subject=find_col(df.columns,cfg['columns']['subject']);site=find_col(df.columns,cfg['columns']['body_site'])
    expected,resolved,missing=resolve_wavelengths(df,cfg)
    if subject is None or site is None or missing:raise RuntimeError(f'Unresolved inputs subject={subject} site={site} missing={missing}')
    wavelengths=[w for w,_ in resolved];cols=[c for _,c in resolved]
    X,scale=normalize(df[cols].apply(pd.to_numeric,errors='coerce'),cfg)
    valid = (
        X.notna().all(axis=1)
        & (
            (X >= float(cfg["reflectance"]["physical_min"]))
            & (X <= float(cfg["reflectance"]["physical_max"]))
        ).all(axis=1)
    )
    meta=df.loc[valid,[subject,site]].copy();meta['_subject']=meta[subject].astype('string');meta['_site']=meta[site].astype('string')
    Xv=X.loc[valid]
    ss=pd.concat([meta[['_subject','_site']],Xv],axis=1).groupby(['_subject','_site'],as_index=False)[cols].mean()
    ncomp=int(cfg['analysis']['components']);B=int(cfg['analysis']['bootstrap_iterations']);rng=np.random.default_rng(int(cfg['analysis']['bootstrap_seed']));minsub=int(cfg['analysis']['minimum_subjects_per_site']);floor=float(cfg['reflectance']['log_floor']);mass=float(cfg['analysis']['loading_mass_fraction'])
    load_rows=[];stab_rows=[];corr_rows=[];site_rows=[];sign_rows=[];refs={}
    for st,g in ss.groupby('_site'):
        if len(g)<minsub:continue
        A=g[cols].to_numpy(float);C=A-A.mean(0);p=PCA(n_components=ncomp,svd_solver='full');scores=p.fit_transform(C);ref=p.components_.copy();refs[str(st)]=ref;D=descriptors(A,wavelengths,floor)
        for k in range(ncomp):
            for d in D.columns:
                r=float(np.corrcoef(scores[:,k],D[d].to_numpy(float))[0,1])
                corr_rows.append({'body_site':str(st),'component':k+1,'descriptor':d,'correlation':r,'absolute_correlation':abs(r),'subjects':len(g)})
            lo,hi,ach=mass_interval(ref[k],wavelengths,mass)
            site_rows.append({'body_site':str(st),'component':k+1,'subjects':len(g),'explained_variance_ratio':float(p.explained_variance_ratio_[k]),'loading_mass_interval_low_nm':lo,'loading_mass_interval_high_nm':hi,'loading_mass_fraction_achieved':ach})
        boot=np.empty((B,ncomp,len(wavelengths)))
        for b in range(B):
            idx=rng.integers(0,len(A),len(A));Cb=A[idx]-A[idx].mean(0);pb=PCA(n_components=ncomp,svd_solver='full').fit(Cb);al,sg=align(ref,pb.components_);boot[b]=al
            for k,s in enumerate(sg,1):sign_rows.append({'body_site':str(st),'bootstrap_iteration':b+1,'component':k,'sign_alignment':s})
        for k in range(ncomp):
            cos=np.array([cosine(ref[k],row) for row in boot[:,k,:]])
            stab_rows.append({'body_site':str(st),'component':k+1,'bootstrap_iterations':B,'reference_bootstrap_cosine_mean':float(cos.mean()),'reference_bootstrap_cosine_p2_5':float(np.quantile(cos,.025)),'reference_bootstrap_cosine_p50':float(np.quantile(cos,.5)),'reference_bootstrap_cosine_p97_5':float(np.quantile(cos,.975)),'reference_bootstrap_cosine_p99':float(np.quantile(cos,.99))})
            for j,w in enumerate(wavelengths):
                v=boot[:,k,j];sgn=np.sign(ref[k,j])
                load_rows.append({'body_site':str(st),'component':k+1,'wavelength_nm':w,'reference_loading':float(ref[k,j]),'bootstrap_mean':float(v.mean()),'bootstrap_std':float(v.std()),'p2_5':float(np.quantile(v,.025)),'p50':float(np.quantile(v,.5)),'p97_5':float(np.quantile(v,.975)),'p99':float(np.quantile(v,.99)),'same_sign_fraction':float(np.mean(np.sign(v)==sgn))})
    load=pd.DataFrame(load_rows);stab=pd.DataFrame(stab_rows);corr=pd.DataFrame(corr_rows);site_df=pd.DataFrame(site_rows);sign_df=pd.DataFrame(sign_rows)
    summary_rows=[]
    for (k,d),g in corr.groupby(['component','descriptor']):
        summary_rows.append({'component':int(k),'descriptor':d,'sites':int(g.body_site.nunique()),'median_correlation':float(g.correlation.median()),'median_absolute_correlation':float(g.absolute_correlation.median()),'p2_5_absolute_correlation':float(g.absolute_correlation.quantile(.025)),'p50_absolute_correlation':float(g.absolute_correlation.quantile(.5)),'p97_5_absolute_correlation':float(g.absolute_correlation.quantile(.975)),'p99_absolute_correlation':float(g.absolute_correlation.quantile(.99)),'same_direction_site_fraction':float(max((g.correlation>=0).mean(),(g.correlation<=0).mean()))})
    corr_sum=pd.DataFrame(summary_rows)
    cross=[];sites=sorted(refs)
    for k in range(ncomp):
        for i,a in enumerate(sites):
            for b in sites[i+1:]:cross.append({'component':k+1,'body_site_a':a,'body_site_b':b,'absolute_cosine_similarity':abs(cosine(refs[a][k],refs[b][k]))})
    cross=pd.DataFrame(cross)
    dom=[]
    for k in range(1,ncomp+1):
        q=corr_sum[corr_sum.component==k].sort_values(['median_absolute_correlation','same_direction_site_fraction'],ascending=False).iloc[0]
        dom.append({'component':k,'dominant_descriptor':q.descriptor,'median_absolute_correlation':float(q.median_absolute_correlation),'p2_5_absolute_correlation':float(q.p2_5_absolute_correlation),'p97_5_absolute_correlation':float(q.p97_5_absolute_correlation),'p99_absolute_correlation':float(q.p99_absolute_correlation),'same_direction_site_fraction':float(q.same_direction_site_fraction)})
    dom=pd.DataFrame(dom)
    for dfout,name in [(load,'bootstrap_wavelength_loadings'),(stab,'bootstrap_loading_stability'),(corr,'site_component_descriptor_correlations'),(corr_sum,'descriptor_correlation_summary'),(site_df,'site_component_summary'),(cross,'cross_site_component_similarity'),(sign_df,'bootstrap_sign_alignment'),(dom,'dominant_component_descriptor')]:write_table(dfout,out/name)
    pc1cross=cross[cross.component==1].absolute_cosine_similarity;pc1stab=stab[stab.component==1].reference_bootstrap_cosine_p2_5;pc1=dom[dom.component==1].iloc[0]
    gates={'stage6_status_admissible':s6.get('status') in allowed,'stage6_site_specific_basis_inherited':s6.get('preferred_representation')=='site_specific_basis','stage6_compact_dimension_inherited':s6.get('registered_compact_component_count')==ncomp,'canonical_row_count_match':len(df)==int(cfg['expected']['canonical_rows']),'subject_count_match':meta._subject.nunique()==int(cfg['expected']['subject_ids']),'body_site_level_count_match':meta._site.nunique()==int(cfg['expected']['body_site_levels']),'wavelength_grid_exact':wavelengths==expected,'all_sites_analyzed':len(refs)==int(cfg['expected']['body_site_levels']),'bootstrap_complete':len(stab)==len(refs)*ncomp,'pc1_bootstrap_loading_stable':float(pc1stab.min())>=float(cfg['analysis']['minimum_pc1_bootstrap_cosine_p2_5']),'pc1_cross_site_loading_consistent':float(pc1cross.min())>=float(cfg['analysis']['minimum_pc1_cross_site_absolute_cosine']),'pc1_descriptor_association_strong':float(pc1.median_absolute_correlation)>=float(cfg['analysis']['minimum_pc1_descriptor_absolute_correlation']),'tail_statistics_computed':load[['p2_5','p50','p97_5','p99']].notna().all().all() and corr_sum[['p2_5_absolute_correlation','p50_absolute_correlation','p97_5_absolute_correlation','p99_absolute_correlation']].notna().all().all()}
    status='CLOSED_WITH_SCOPE_LIMITATION' if all(gates.values()) else 'OPEN_FAILED_GATES'
    summary=native({'stage':7,'name':'dominant_axis_interpretation_and_wavelength_attribution','status':status,'canonical_path':str(args.canonical_file),'canonical_sha256':sha256_file(args.canonical_file),'canonical_rows':len(df),'admissible_rows':int(valid.sum()),'subjects':int(meta._subject.nunique()),'body_site_levels':int(meta._site.nunique()),'wavelength_count':len(wavelengths),'components_interpreted':ncomp,'bootstrap_iterations_per_site':B,'pc1_dominant_descriptor':str(pc1.dominant_descriptor),'pc1_median_absolute_descriptor_correlation':float(pc1.median_absolute_correlation),'pc1_cross_site_absolute_cosine_min':float(pc1cross.min()),'pc1_cross_site_absolute_cosine_median':float(pc1cross.median()),'pc1_cross_site_absolute_cosine_p97_5':float(pc1cross.quantile(.975)),'pc1_cross_site_absolute_cosine_p99':float(pc1cross.quantile(.99)),'pc1_bootstrap_cosine_p2_5_min':float(pc1stab.min()),'component_descriptor_adjudication':dom.to_dict('records'),'biological_identity_resolved':False,'global_subject_tone_scalar_admissible':False,'analysis_unit':'body_location_code_conditioned_spectrum','inherited_scope_limitations':s6.get('inherited_scope_limitations',[]),'gates':gates,'hard_failed_gates':[k for k,v in gates.items() if not v],'next_stage':{'id':8,'name':'wavelength_reduction_and_external_colorimetric_validation','inherited_restrictions':s6.get('next_stage',{}).get('inherited_restrictions',[])} if all(gates.values()) else None})

    # Reproduce the least-similar PC1 cross-site loading pair.
    pc1_pair_candidates = (
        cross[
            cross["component"] == 1
        ]
        .sort_values(
            "absolute_cosine_similarity"
        )
    )

    if pc1_pair_candidates.empty:
        raise RuntimeError(
            "PC1 cross-site comparison unavailable."
        )

    limiting_pair = pc1_pair_candidates.iloc[0]


    def canonical_stage7_site(value):
        try:
            numeric = float(value)

            if numeric.is_integer():
                return str(int(numeric))
        except (TypeError, ValueError):
            pass

        return str(value).strip()


    site_a = canonical_stage7_site(
        limiting_pair["body_site_a"]
    )
    site_b = canonical_stage7_site(
        limiting_pair["body_site_b"]
    )

    loading_site_keys = (
        load["body_site"]
        .map(canonical_stage7_site)
    )

    loading_columns = [
        "wavelength_nm",
        "reference_loading",
        "p2_5",
        "p50",
        "p97_5",
        "p99",
    ]

    limiting_a = load[
        (load["component"] == 1)
        & (loading_site_keys == site_a)
    ][loading_columns].copy()

    limiting_b = load[
        (load["component"] == 1)
        & (loading_site_keys == site_b)
    ][loading_columns].copy()

    if len(limiting_a) != len(wavelengths):
        raise RuntimeError(
            "PC1 limiting site A wavelength rows="
            f"{len(limiting_a)}"
        )

    if len(limiting_b) != len(wavelengths):
        raise RuntimeError(
            "PC1 limiting site B wavelength rows="
            f"{len(limiting_b)}"
        )

    limiting_comparison = limiting_a.merge(
        limiting_b,
        on="wavelength_nm",
        suffixes=("_a", "_b"),
        validate="one_to_one",
    )

    limiting_dot = float(
        (
            limiting_comparison[
                "reference_loading_a"
            ]
            * limiting_comparison[
                "reference_loading_b"
            ]
        ).sum()
    )

    limiting_sign_flipped = limiting_dot < 0

    if limiting_sign_flipped:
        for column in [
            "reference_loading_b",
            "p2_5_b",
            "p50_b",
            "p97_5_b",
            "p99_b",
        ]:
            limiting_comparison[column] *= -1

    limiting_comparison[
        "absolute_loading_difference"
    ] = (
        limiting_comparison[
            "reference_loading_a"
        ]
        - limiting_comparison[
            "reference_loading_b"
        ]
    ).abs()

    limiting_denominator = (
        0.5
        * (
            limiting_comparison[
                "reference_loading_a"
            ].abs()
            + limiting_comparison[
                "reference_loading_b"
            ].abs()
        )
    )

    limiting_comparison[
        "relative_absolute_difference"
    ] = (
        limiting_comparison[
            "absolute_loading_difference"
        ]
        / limiting_denominator.replace(
            0,
            np.nan,
        )
    )

    limiting_comparison.insert(
        0,
        "body_site_b",
        site_b,
    )
    limiting_comparison.insert(
        0,
        "body_site_a",
        site_a,
    )

    write_table(
        limiting_comparison,
        out / "pc1_limiting_pair_loading_comparison",
    )

    summary["pc1_limiting_pair"] = {
        "body_site_a": site_a,
        "body_site_b": site_b,
        "absolute_cosine_similarity": float(
            limiting_pair[
                "absolute_cosine_similarity"
            ]
        ),
        "sign_flipped_for_comparison": bool(
            limiting_sign_flipped
        ),
        "wavelengths_compared": int(
            len(limiting_comparison)
        ),
    }

    (out/'stage7_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True));(out/'STAGE_7_CLOSED.yaml').write_text(yaml.safe_dump(summary,sort_keys=False))
    (out/'wavelength_attribution_report.md').write_text(f"# ISSA Stage 7 Wavelength Attribution\n\nStatus: **{status}**\n\n- PC1 dominant descriptor: {summary['pc1_dominant_descriptor']}\n- PC1 median absolute descriptor correlation: {summary['pc1_median_absolute_descriptor_correlation']}\n- PC1 minimum cross-site absolute cosine: {summary['pc1_cross_site_absolute_cosine_min']}\n- PC1 minimum bootstrap cosine p2.5: {summary['pc1_bootstrap_cosine_p2_5_min']}\n\nBiological identity remains unresolved. Body-site conditioning remains mandatory.\n")
    manifest=[]
    for p in sorted(out.iterdir()):
        if p.is_file():manifest.append({'file':p.name,'sha256':sha256_file(p),'bytes':p.stat().st_size})
    pd.DataFrame(manifest).to_csv(out/'sha256_manifest.csv',index=False)
    print(json.dumps(summary,indent=2,sort_keys=True));return 0 if status=='CLOSED_WITH_SCOPE_LIMITATION' else 2
if __name__=='__main__':raise SystemExit(main())
