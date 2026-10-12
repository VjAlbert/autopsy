from drdeconstruct.core.detect import guess
from drdeconstruct.core.types import ArtifactKind
from drdeconstruct.preprocess.chunker import split_c_functions

SRC = """
undefined4 FUN_00010000(int param_1)
{
  if (param_1 == 0) {
    return 1;
  }
  return FUN_00010040(param_1 - 1);
}

void FUN_00010040(int a)
{
  int x;
  x = a * 2;
}
"""


def test_split_two_functions():
    chunks = split_c_functions(SRC)
    assert [c.name for c in chunks] == ["FUN_00010000", "FUN_00010040"]
    assert chunks[0].code.rstrip().endswith("}")
    assert "x = a * 2" in chunks[1].code


def test_guess_c_and_asm():
    assert guess(SRC).kind is ArtifactKind.PSEUDOCODE_C
    asm = "00401000: push ebp\n00401001: mov ebp, esp\n00401003: call 0x401100\n"
    assert guess(asm).kind is ArtifactKind.ASSEMBLY
