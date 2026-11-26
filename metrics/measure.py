#!/usr/bin/env python3
"""Mede o acoplamento de app/helpdesk/ segundo a régua fixa do desafio (req. 3).

Uso:
    python metrics/measure.py <caminho/para/app/helpdesk> --name v1-coupled

Gera:
    metrics/results/<name>.csv   cabeçalho exato: component,ca,ce,i,a,d
    metrics/results/<name>.png   gráfico A x I com a Main Sequence traçada

Régua (fixa, para que todas as medições sejam comparáveis):
  - componente = cada módulo .py de helpdesk/ (inclui subpastas), identificado
    pelo caminho com pontos (ex.: adapters.gateway), EXCETO os __init__.py;
  - dependência = um import (relativo ou absoluto) que resolve para OUTRO
    componente; libs externas e da biblioteca padrão NÃO contam;
  - Ca = quantos componentes importam este; Ce = quantos este importa;
  - I  = Ce / (Ce + Ca), ou 0 quando ambos são zero;
  - A  = nº de classes abstratas (herdam de typing.Protocol ou abc.ABC)
         dividido pelo total de classes do módulo, ou 0 se não há classes;
  - D  = |A + I - 1|;
  - valores arredondados para 2 casas.
"""

import argparse
import ast
import csv
import pathlib
import sys


def discover_components(root: pathlib.Path) -> dict[str, pathlib.Path]:
    """Mapeia nome-de-componente (caminho com pontos, sem .py) -> arquivo.

    __init__.py é excluído. O nome é relativo à raiz do pacote medido
    (ex.: helpdesk/adapters/gateway.py -> 'adapters.gateway').
    """
    components: dict[str, pathlib.Path] = {}
    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(root).with_suffix("")
        name = ".".join(rel.parts)
        components[name] = path
    return components


def module_package(name: str) -> list[str]:
    """Pacote que contém o módulo (partes do nome sem o último segmento)."""
    return name.split(".")[:-1]


def resolve_imports(name: str, tree: ast.AST, components: set[str], package_name: str) -> set[str]:
    """Componentes internos que o módulo `name` importa (distintos, != ele mesmo)."""
    deps: set[str] = set()
    pkg = module_package(name)

    def consider(candidate_parts: list[str], extra_names: list[str]) -> None:
        """Dado um alvo de import já relativo à raiz do pacote, registra deps.

        candidate_parts é o caminho do módulo/pacote alvo (sem o nome do pacote
        raiz). extra_names são nomes importados dele (podem ser submódulos).
        """
        dotted = ".".join(candidate_parts)
        if dotted and dotted in components:
            # Import de objetos de um módulo: o módulo é a dependência.
            deps.add(dotted)
            return
        # O alvo pode ser um pacote; cada nome importado pode ser um submódulo.
        for n in extra_names:
            sub = ".".join(candidate_parts + [n]) if candidate_parts else n
            if sub in components:
                deps.add(sub)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names] if node.names else []
            if node.level and node.level > 0:
                # Import relativo: ancora no pacote do módulo, sobe (level-1).
                up = node.level - 1
                anchor = pkg[: len(pkg) - up] if up <= len(pkg) else []
                mod_parts = node.module.split(".") if node.module else []
                consider(anchor + mod_parts, names)
            elif node.module:
                # Import absoluto. Só interessa se começa pelo pacote raiz.
                parts = node.module.split(".")
                if parts and parts[0] == package_name:
                    consider(parts[1:], names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts and parts[0] == package_name:
                    consider(parts[1:], [])

    deps.discard(name)
    return deps


def abstractness(tree: ast.AST) -> float:
    """A = classes abstratas / total de classes (0 se não há classes)."""
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    if not classes:
        return 0.0
    abstract = 0
    for cls in classes:
        bases: list[str] = []
        for base in cls.bases:
            bases.append(base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", ""))
        # typing.Protocol (ou Protocol) e abc.ABC (ou ABC).
        if any(b in {"Protocol", "ABC"} for b in bases):
            abstract += 1
    return abstract / len(classes)


def measure(root: pathlib.Path) -> list[dict]:
    components = discover_components(root)
    names = set(components)
    package_name = root.name  # ex.: 'helpdesk'

    trees: dict[str, ast.AST] = {}
    ce_sets: dict[str, set[str]] = {}
    for name, path in components.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[name] = tree
        ce_sets[name] = resolve_imports(name, tree, names, package_name)

    # Ca: quantos importam cada componente.
    ca: dict[str, int] = {name: 0 for name in names}
    for name, deps in ce_sets.items():
        for dep in deps:
            ca[dep] += 1

    rows = []
    for name in sorted(names):
        ce = len(ce_sets[name])
        ca_v = ca[name]
        i = ce / (ce + ca_v) if (ce + ca_v) else 0.0
        a = abstractness(trees[name])
        d = abs(a + i - 1)
        rows.append(
            {
                "component": name,
                "ca": ca_v,
                "ce": ce,
                "i": round(i, 2),
                "a": round(a, 2),
                "d": round(d, 2),
            }
        )
    return rows


def write_csv(rows: list[dict], out: pathlib.Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["component", "ca", "ce", "i", "a", "d"])
        writer.writeheader()
        writer.writerows(rows)


def write_plot(rows: list[dict], out: pathlib.Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 7))
    # Main Sequence: A + I = 1.
    ax.plot([0, 1], [1, 0], color="#2E7D32", linestyle="--", label="Main Sequence (A + I = 1)")
    # Zonas: dor (canto inferior esquerdo) e inutilidade (canto superior direito).
    ax.add_patch(plt.Rectangle((0, 0), 0.5, 0.5, color="#D32F2F", alpha=0.08))
    ax.add_patch(plt.Rectangle((0.5, 0.5), 0.5, 0.5, color="#616161", alpha=0.08))
    ax.text(0.02, 0.02, "zona de dor", color="#D32F2F", fontsize=9, alpha=0.8)
    ax.text(0.72, 0.95, "zona de inutilidade", color="#616161", fontsize=9, alpha=0.8)

    for r in rows:
        ax.scatter(r["i"], r["a"], color="#1565C0", zorder=3)
        ax.annotate(
            r["component"],
            (r["i"], r["a"]),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=8,
        )

    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("I — Instabilidade (Ce / (Ce + Ca))")
    ax.set_ylabel("A — Abstração")
    ax.set_title(title)
    ax.legend(loc="upper center")
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Métrica de acoplamento (Main Sequence).")
    parser.add_argument("path", help="caminho para a pasta helpdesk/ a medir")
    parser.add_argument("--name", required=True, help="nome da medição (ex.: v1-coupled)")
    parser.add_argument(
        "--results-dir",
        default=str(pathlib.Path(__file__).parent / "results"),
        help="diretório de saída (padrão: metrics/results)",
    )
    args = parser.parse_args(argv)

    root = pathlib.Path(args.path).resolve()
    if not root.is_dir():
        print(f"erro: {root} não é um diretório", file=sys.stderr)
        return 2

    rows = measure(root)
    results_dir = pathlib.Path(args.results_dir)
    write_csv(rows, results_dir / f"{args.name}.csv")
    write_plot(rows, results_dir / f"{args.name}.png", f"Main Sequence — {args.name}")

    # Eco no terminal para conferência rápida.
    print(f"{'component':<16} ca ce   i    a    d")
    for r in rows:
        print(f"{r['component']:<16} {r['ca']:>2} {r['ce']:>2} {r['i']:.2f} {r['a']:.2f} {r['d']:.2f}")
    print(f"\nescrito: {results_dir / (args.name + '.csv')}")
    print(f"escrito: {results_dir / (args.name + '.png')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
