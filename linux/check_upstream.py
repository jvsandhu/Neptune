"""Report upstream drift without modifying the checkout or merging anything.

Prefer the original project's `upstream` remote in a fork checkout; retain
`origin` as the fallback for a direct clone of the original repository.
"""
import argparse
import json
import subprocess
from pathlib import Path


def select_target(remotes, remote=None, ref=None):
    """Choose the original project by default, not the fork's main branch."""
    if remote is None:
        ref_remote = ref.split('/', 1)[0] if ref else None
        remote = ref_remote if ref_remote in remotes else (
            'upstream' if 'upstream' in remotes else 'origin'
        )
    if remote not in remotes:
        raise ValueError(f'Unknown remote: {remote}. Configure it or pass --remote NAME.')
    return remote, ref or f'{remote}/main'


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--remote', help='Remote to fetch (default: upstream, otherwise origin)')
    parser.add_argument('--ref', help='Revision to inspect (default: selected remote/main)')
    args = parser.parse_args(argv)

    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=root, text=True).strip()

    try:
        remote, ref = select_target(git('remote').splitlines(), args.remote, args.ref)
    except ValueError as error:
        parser.error(str(error))
    lock = json.loads((root / 'linux/upstream.json').read_text())
    if args.fetch:
        subprocess.run(['git', 'fetch', remote], cwd=root, check=True)
    head = git('rev-parse', '--verify', f'{ref}^{{commit}}')
    changed = git('diff', '--name-only', lock['revision'], head).splitlines()
    review = sorted(set(changed) & set(lock['watched_files']))
    print(json.dumps({
        'remote': remote,
        'ref': ref,
        'tested_upstream': lock['revision'],
        'candidate': head,
        'changed_files': changed,
        'platform_contract_review': review,
        'working_tree_modified': bool(git('status', '--porcelain')),
        'action': 'No merge performed. Review all changed files, merge in a working branch, '
                  'run Linux tests and visual/live validation before advancing the pin.',
    }, indent=2))


if __name__ == '__main__':
    main()
