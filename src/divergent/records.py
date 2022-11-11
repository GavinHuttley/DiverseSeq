"""summed records contain multiple SeqRecord instances. This container class
efficiently computes jsd

I laid this out in my comment https://github.com/GavinHuttley/BIOL3208-bensilke/issues/34#issuecomment-1105874023

convert a sequence collection into a SummedRecords instance, which supports
the following applications

Find N
-------
identify the N'th most divergent sequences

Most divergent
--------------
identify the set of sequences that maximise delta-JSD


SummedRecords is the container that simplifies these applications

"""
from functools import singledispatch
from math import fsum
from typing import Union

from attrs import define, field
from numpy import isclose as np_isclose
from numpy import isnan, log2, ndarray, zeros
from rich.progress import track

from divergent.record import SeqRecord, sparse_vector


# needs a jsd method for a new sequence
# needs summed entropy scores
# needs combined array of summed freqs to allow efficient calculation of entropy
# on creation, computes total JSD, then delta_jsd (contribution of each sequence)
# seq records sorted by the latter; stored summed quantities for n and n-1 (with
# the least contributor omitted)


@singledispatch
def _jsd(
    summed_freqs: Union[sparse_vector, ndarray], summed_entropy: float, n: int
) -> float:
    raise NotImplementedError


@_jsd.register
def _(summed_freqs: sparse_vector, summed_entropy: float, n: int):
    kfreqs = summed_freqs / n
    entropy = summed_entropy / n
    return kfreqs.entropy - entropy


@_jsd.register
def _(summed_freqs: ndarray, summed_entropy: float, n: int):
    kfreqs = summed_freqs / n
    entropy = summed_entropy / n
    kfreqs = kfreqs[~np_isclose(kfreqs, 0)]
    ke = -(kfreqs * log2(kfreqs)).sum()
    return ke - entropy


def _summed_stats(records: list[SeqRecord]) -> tuple[sparse_vector, float]:
    # takes series of records and sums quantitative parts
    sv = records[0].kfreqs
    vec = zeros(len(sv), dtype=float)
    entropies = []
    for record in records:
        vec += record.kfreqs
        entropies.append(record.entropy)

    vec = sparse_vector(data=vec, vector_length=len(vec), dtype=float)
    return vec, fsum(entropies)


def _delta_jsd(
    total_kfreqs: sparse_vector,
    total_entropies: float,
    records: list[SeqRecord],
) -> list[SeqRecord]:
    """measures contribution of each record to the total JSD"""
    n = len(records)
    total_jsd = _jsd(total_kfreqs, total_entropies, n)
    total_kfreqs = total_kfreqs.array
    result = []
    for record in records:
        summed_kfreqs = total_kfreqs - record.kfreqs.array
        summed_entropies = total_entropies - record.entropy
        jsd = _jsd(summed_kfreqs, summed_entropies, n - 1)
        record.delta_jsd = total_jsd - jsd
        if isnan(record.delta_jsd):
            print(f"{record.name!r} had a nan")
            exit(1)
        result.append(record)
    return result


def _check_integrity(instance, attribute, records: list[SeqRecord]):
    last = records[0]
    for r in records[1:]:
        if r.delta_jsd < last.delta_jsd:
            raise RuntimeError


@define
class SummedRecords:
    """use the from_records clas method to construct the instance"""

    # we need the records to have been sorted by delta_jsd
    # following check is in place for now until fully tested
    # todo delete when convinced no longer required

    records: list[SeqRecord] = field(validator=_check_integrity)
    summed_kfreqs: sparse_vector
    summed_entropies: float
    total_jsd: float
    size: int = field(init=False)
    record_names: set = field(init=False)
    lowest: SeqRecord = field(init=False)

    def __init__(
        self,
        records: list[SeqRecord],
        summed_kfreqs: sparse_vector,
        summed_entropies: float,
        total_jsd: float,
    ):
        self.record_names = {r.name for r in records}
        self.total_jsd = total_jsd
        self.lowest = records[0]
        self.records = records[1:]
        self.size = len(records)
        # NOTE we exclude lowest record from freqs and entropy
        self.summed_kfreqs = summed_kfreqs - self.lowest.kfreqs
        self.summed_entropies = summed_entropies - self.lowest.entropy

    @classmethod
    def from_records(cls, records: list[:SeqRecord]):
        size = len(records)
        summed_kfreqs, summed_entropies = _summed_stats(records)
        total_jsd = _jsd(summed_kfreqs, summed_entropies, size)
        records = sorted(
            _delta_jsd(summed_kfreqs, summed_entropies, records),
            key=lambda x: x.delta_jsd,
        )
        return cls(records, summed_kfreqs, summed_entropies, total_jsd)

    def _make_new(
        self,
        records: list[:SeqRecord],
        summed_kfreqs: sparse_vector,
        summed_entropies: float,
    ):
        """summed are totals from all records"""
        size = len(records)
        total_jsd = _jsd(summed_kfreqs, summed_entropies, size)
        records = sorted(
            _delta_jsd(
                summed_kfreqs,
                summed_entropies,
                records,
            ),
            key=lambda x: x.delta_jsd,
        )
        return self.__class__(records, summed_kfreqs, summed_entropies, total_jsd)

    def __contains__(self, item: SeqRecord):
        return item.name in self.record_names

    def __add__(self, other: SeqRecord):
        assert other not in self
        summed_kfreqs = self.summed_kfreqs + self.lowest.kfreqs + other.kfreqs
        summed_entropies = self.summed_entropies + self.lowest.entropy + other.entropy
        return self._make_new(
            [self.lowest, other] + list(self.records),
            summed_kfreqs,
            summed_entropies,
        )

    def __sub__(self, other: SeqRecord):
        assert other in self
        records = [r for r in self.records + [self.lowest] if r is not other]
        if len(records) != len(self.records):
            raise ValueError(
                f"cannot subtract record {other.name!r}, not present in self"
            )

        summed_kfreqs = self.summed_kfreqs + self.lowest.kfreqs - other.kfreqs
        summed_entropies = self.summed_entropies + self.lowest.entropy - other.entropy
        return self._make_new(records, summed_kfreqs, summed_entropies)

    def iter_record_names(self):
        for name in self.record_names:
            yield name

    def increases_jsd(self, record: SeqRecord) -> bool:
        # whether total JSD increases when record is used
        j = _jsd(
            self.summed_kfreqs + record.kfreqs,
            self.summed_entropies + record.entropy,
            self.size,
        )
        return self.total_jsd < j

    @property
    def mean_jsd(self):
        return self.total_jsd / self.size

    @property
    def mean_delta_jsd(self):
        total = fsum([fsum(r.delta_jsd for r in self.records), self.lowest.delta_jsd])
        return total / (len(self.records) + 1)

    def replaced_lowest(self, other: SeqRecord):
        """returns new SummedRecords with other instead of lowest"""
        summed_kfreqs = self.summed_kfreqs + other.kfreqs
        summed_entropies = self.summed_entropies + other.entropy
        return self._make_new([other] + self.records, summed_kfreqs, summed_entropies)


def max_divergent(
    records: list[SeqRecord],
    min_size: int = 2,
    max_size: int = None,
    stat: str = "mean_jsd",
    max_set: bool = True,
    verbose: bool = False,
) -> SummedRecords:
    """returns SummedRecords that maximises mean stat

    Parameters
    ----------
    records
        list of SeqRecord instances
    min_size
        starting size of SummedRecords
    max_size
        defines upper limit of SummedRecords size
    stat
        either mean_delta_jsd, mean_jsd, total_jsd
    max_set
        postprocess to identify subset that maximises stat
    Notes
    -----
    This is sensitive to the order of records.
    """
    min_size = min_size or 2
    max_size = max_size or len(records)
    sr = SummedRecords.from_records(records[:min_size])
    if stat not in ("mean_jsd", "mean_delta_jsd", "total_jsd"):
        raise ValueError(f"unknown value of stat {stat}")

    if len(records) <= min_size:
        return sr

    series = track(records, transient=True) if verbose else records
    for r in series:
        if r in sr:
            continue

        if not sr.increases_jsd(r):
            continue

        nsr = sr + r
        sr = nsr if getattr(nsr, stat) > getattr(sr, stat) else sr.replaced_lowest(r)
        if sr.size > max_size:
            sr = SummedRecords.from_records(sr.records)

    if max_set:
        sr = _maximal_stat(sr, verbose, stat, min_size)
    elif verbose:
        num_neg = sum(r.delta_jsd < 0 for r in [sr.lowest] + sr.records)
        print(f"Records with delta_jsd < 0 is {num_neg}")
    return sr


def _maximal_stat(
    sr: SummedRecords, verbose: bool, stat: str, size: int
) -> SummedRecords:
    if sr.size == 2:
        return sr

    results = {getattr(sr, stat): sr}
    orig_size = sr.size
    orig_stat = getattr(sr, stat)

    while sr.size > size:
        sr = sr.from_records(sr.records)
        results[getattr(sr, stat)] = sr

    sr = results[max(results)]

    if verbose:
        print(
            f"Reduced size from {orig_size} to {sr.size}",
            f" Increased {stat} from {orig_stat:.3f} to {getattr(sr, stat):.3f}",
            sep="\n",
        )
    return sr


def most_divergent(
    records: list[SeqRecord], size: int, verbose: bool = False
) -> SummedRecords:
    """returns size most divergent records

    Parameters
    ----------
    records
        list of SeqRecord instances
    size
        starting size of SummedRecords

    """
    size = size or 2
    sr = SummedRecords.from_records(records[:size])

    if len(records) <= size:
        return sr

    for r in track(records):
        if r in sr:
            continue

        if not sr.increases_jsd(r):
            continue

        sr = sr.replaced_lowest(r)

    if verbose:
        num_neg = sum(r.delta_jsd < 0 for r in [sr.lowest] + sr.records)
        print(f"number negative is {num_neg}")
    return sr
