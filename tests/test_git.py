from corral import git


def make_repo(root, head="ref: refs/heads/main\n"):
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(head)
    return root


def test_branch_of_repo_and_its_subfolders(tmp_path):
    repo = make_repo(tmp_path / "proj", "ref: refs/heads/feat/usage-charts\n")
    (repo / "src" / "deep").mkdir(parents=True)
    assert git.branch(str(repo)) == "feat/usage-charts"
    assert git.branch(str(repo / "src" / "deep")) == "feat/usage-charts"


def test_branch_of_worktree_follows_its_gitdir(tmp_path):
    make_repo(tmp_path / "proj")
    gitdir = tmp_path / "proj" / ".git" / "worktrees" / "fix"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/worktree-fix\n")
    tree = tmp_path / "proj" / ".claude" / "worktrees" / "fix"
    tree.mkdir(parents=True)
    (tree / ".git").write_text(f"gitdir: {gitdir}\n")
    assert git.branch(str(tree)) == "worktree-fix"


def test_branch_of_relative_gitdir(tmp_path):
    gitdir = tmp_path / "store" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/dev\n")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / ".git").write_text("gitdir: ../store/wt\n")
    assert git.branch(str(tree)) == "dev"


def test_detached_head_shows_short_sha(tmp_path):
    repo = make_repo(tmp_path / "proj", "0123456789abcdef0123456789abcdef01234567\n")
    assert git.branch(str(repo)) == "0123456"


def test_no_branch_outside_a_repo_or_for_broken_git(tmp_path):
    assert git.branch(str(tmp_path)) == ""
    assert git.branch("") == ""
    assert git.branch(str(tmp_path / "missing")) == ""
    (tmp_path / "bad" / ".git").mkdir(parents=True)  # no HEAD
    assert git.branch(str(tmp_path / "bad")) == ""
