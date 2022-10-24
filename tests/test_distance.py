import pytest

from numpy import array
from numpy.testing import assert_allclose

from divergent.distance import _intersect_union, jaccard
from divergent.record import unique_kmers


def _make_sample(type_):
    if type_ != unique_kmers:
        return type_([0, 1, 3]), type_([1, 4, 5])

    i, u = _make_sample(array)
    kwargs = dict(num_states=4, k=1)
    return unique_kmers(data=i, **kwargs), unique_kmers(data=u, **kwargs)


@pytest.mark.parametrize(
    "rec1,rec2", (_make_sample(set), _make_sample(array), _make_sample(unique_kmers))
)
def test_intersect_union(rec1, rec2):
    i, u = _intersect_union(rec1, rec2)
    assert i == 1 and u == 5


@pytest.mark.parametrize(
    "rec1,rec2,exp",
    (
        [{1, 2}, {3, 4}, 1],
        [set(), {1}, 1],
        [{1}, set(), 1],
        [{1, 2}, {1, 2}, 0],
        [{1, 2}, {1, 3}, 2 / 3],
    ),
)
def test_jaccard(rec1, rec2, exp):
    assert_allclose(jaccard(rec1, rec2), exp)