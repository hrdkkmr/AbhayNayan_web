"""Import before numpy/sklearn. Single-threaded BLAS/OpenMP keeps fits bit-reproducible: the colour features
are nearly collinear, and multithreaded summation order changed the logistic-regression solution between runs."""
import os

for _var in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_var, '1')
