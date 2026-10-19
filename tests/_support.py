"""Test-only routing fixtures; these are not third-party writing guidance."""
from pathlib import Path
import shutil

def fixture_skills(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    own=Path(__file__).resolve().parents[1]/'skills/mathm-latex-writing'
    shutil.copytree(own,destination/'mathm-latex-writing')
    names=['hwb-problem-translator','hwb-modeling-ideas','hwb-model-dictionary','hwb-abstract-checker','hwb-model-solution-checker','hwb-reference-appendix-checker','nature-writing','nature-polishing']
    for name in names:
        folder=destination/name;folder.mkdir();(folder/'SKILL.md').write_text('Test fixture only. Never use as real writing or review guidance.')
    for name in ['nature-writing','nature-polishing']:
        for path in ['static/core/stance.md','static/core/workflow.md']:
            p=destination/name/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('Test routing fixture.')
    p=destination/'nature-shared/core/discussion-argument-language.md';p.parent.mkdir(parents=True);p.write_text('Test routing fixture.')
    return destination
