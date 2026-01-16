# scripts/smoke_routing.py
# Smoke test: ruteo RMF exact + literal bypass NO rompe leyes y no confunde "Regla N-A" con "Artículo N-A"
import os
import sys
import sys
import argparse
from typing import Any, Dict, Tuple
# Asegura que la raíz del repo esté en sys.path (para importar "app")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app.services.rag_engine import generate_response_with_rag


def run(q: str, ejercicio: int) -> Tuple[str, Dict[str, Any]]:
    r, d = generate_response_with_rag(q, ejercicio=ejercicio, trace=True)
    if not isinstance(d, dict):
        d = {"debug_raw": d}
    return (r or ""), d


def assert_true(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


def pretty_debug(d: Dict[str, Any]) -> str:
    parts = [
        f"route_used={d.get('route_used')}",
        f"used_year={d.get('used_year')}",
        f"evidence_count={d.get('evidence_count')}",
    ]
    sources = d.get("sources") or []
    if sources:
        s0 = sources[0]
        parts.append(
            "source0="
            + f"{s0.get('source')}|{s0.get('document_id')}|{s0.get('norm_kind')}|{s0.get('norm_id')}"
        )
    return ", ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ejercicio", type=int, default=2025)
    args = ap.parse_args()

    ejercicio = args.ejercicio
    failures = 0

    tests = []

    # TEST 1: RMF exact lookup + literal bypass
    tests.append(
        (
            "RMF exact + literal",
            f"Cítame textualmente la Regla 2.1.1 de la RMF {ejercicio}",
            lambda r, d: (
                assert_true(d.get("route_used") == "rmf_rule_lookup", "Debe usar rmf_rule_lookup"),
                assert_true((d.get("evidence_count") or 0) >= 1, "Debe traer evidencia RMF"),
                assert_true(r.lstrip().startswith(">"), "La salida literal debe venir en blockquote (>)"),
                assert_true(
                    any((s.get("source") == "rmf_rule_lookup" and s.get("norm_id") == "2.1.1") for s in (d.get("sources") or [])),
                    "Debe incluir source rmf_rule_lookup con norm_id=2.1.1",
                ),
            ),
        )
    )

    # TEST 2: Ley (article_lookup)
    tests.append(
        (
            "Ley article_lookup (CFF 29-A)",
            "Cítame textualmente el Artículo 29-A del CFF 2025",
            lambda r, d: (
                assert_true(d.get("route_used") == "article_lookup", "Debe usar article_lookup"),
                assert_true((d.get("evidence_count") or 0) >= 1, "Debe traer evidencia del artículo"),
                assert_true(
                    any(
                        (s.get("source") == "article_lookup"
                         and s.get("document_id") == "CODIGO_FISCAL_DE_LA_FEDERACION"
                         and s.get("norm_id") == "29-A")
                        for s in (d.get("sources") or [])
                    ),
                    "Debe traer Art. 29-A desde CODIGO_FISCAL_DE_LA_FEDERACION",
                ),
            ),
        )
    )

    # TEST 3: Regla no estándar (NO confundir con Artículo 29-A)
    tests.append(
        (
            "RMF no estándar (Regla 29-A) no confunde con Artículo",
            f"Cítame textualmente la Regla 29-A de la RMF {ejercicio}",
            lambda r, d: (
                assert_true(d.get("route_used") != "article_lookup", "NO debe caer a article_lookup"),
                assert_true(
                    not any(
                        (s.get("source") == "article_lookup"
                         or s.get("document_id") == "CODIGO_FISCAL_DE_LA_FEDERACION"
                         or s.get("norm_id") == "29-A")
                        for s in (d.get("sources") or [])
                    ),
                    "NO debe traer CFF 29-A ni sources de article_lookup",
                ),
                assert_true(
                    ("No cuento con el fragmento específico" in r)
                    or ((d.get("evidence_count") or 0) == 0),
                    "Debe antialucinar o no traer evidencia (evidence_count=0)",
                ),
                assert_true(
                    not r.lstrip().startswith(">"),
                    "No debe devolver cita literal (blockquote) para una regla inexistente/no localizada",
                ),
            ),
        )
    )

    print(f"\n=== SMOKE ROUTING (ejercicio={ejercicio}) ===")
    for name, q, check in tests:
        try:
            r, d = run(q, ejercicio)
            check(r, d)
            print(f"[PASS] {name} | {pretty_debug(d)}")
        except Exception as e:
            failures += 1
            print(f"[FAIL] {name} | {e}")
            try:
                if isinstance(d, dict):
                    print("       debug:", pretty_debug(d))
            except Exception:
                pass

    if failures:
        print(f"\nFAILURES: {failures}")
        sys.exit(1)

    print("\nALL TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
