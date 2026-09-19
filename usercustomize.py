"""Load fund-analysis enhancements before Streamlit imports function aliases.

Python's site module imports usercustomize after sitecustomize during normal startup.
Keeping activation here avoids changing the existing parser module while the feature
is reviewed on its branch.
"""

try:
    import fund_analysis
    from holdings_enhancement import install

    install(fund_analysis)
except Exception:
    # The base application must remain usable even if optional enrichment cannot load.
    pass
