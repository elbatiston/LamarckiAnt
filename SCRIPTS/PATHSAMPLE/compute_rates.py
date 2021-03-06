"""
Author: Jacob Stevenson js850@cam.ac.uk

Compute rates from a pathsample database.  The rates are computed
by solving a set of linear equations using a sparse solver.

Requirements
------------
Python2.7 and the packages numpy, scipy, and networkx.  
"""
import argparse
import sys
import os
import time
from itertools import izip
import numpy as np
import networkx as nx

from _compute_rates_utils import TwoStateRates, reduce_rates


def log_sum2(a, b):
    """return log( exp(a) + exp(b) )"""
    if a > b:
        return a + np.log(1.0 + np.exp(-a + b) )
    else:
        return b + np.log(1.0 + np.exp(a - b) )

class RatesFromPathsampleDB(object):
    """read minima and ts data from pathsample database and compute rate constants"""
    def __init__(self, mindata_file, tsdata_file, T):
        self.T = T
        self.run(mindata_file, tsdata_file)
    
    def _log_equilibrium_occupation_probabilities(self, mindata):
        """return the log equilibrium occupation probability
        
        This is computed from the harmonic superposition approximation.  Some
        constants that are the same for all minima have been left out.
        """
        energy = mindata[:,0]
        fvib = mindata[:,1]
        pgorder = mindata[:,2]
        return (-energy / self.T - np.log(pgorder) - 0.5 * fvib)
    
    def _compute_log_rates(self, m1vals, tsdata, T):
        menergy = m1vals[:,0]
        mfvib = m1vals[:,1]
        mpgorder = m1vals[:,2]
        tsenergy = tsdata[:,0]
        tsfvib = tsdata[:,1]
        tspgorder = tsdata[:,2]
        return (np.log(mpgorder / (2. * np.pi * tspgorder))
                + (mfvib - tsfvib) / 2. 
                - (tsenergy - menergy) / T)

    def compute_rates(self, mindata, tsdata, mindices):
        """return the array of rates over the transition states
        """
        m1vals = mindata[mindices,:]
        
        assert m1vals.shape[0] == tsdata.shape[0]
        return self._compute_log_rates(m1vals, tsdata, self.T)
    
    def make_rates_dict(self, m1_indices, m2_indices, log_kuv_list, log_kvu_list):
        """turn the arrays into a dictionary of rates"""
        log_rates = dict()
        assert m1_indices.size == m2_indices.size == log_kuv_list.size == log_kvu_list.size
        
        
        for u, v, log_kuv, log_kvu in izip(m1_indices, m2_indices, 
                                           log_kuv_list, log_kvu_list):
            if u == v:
                # don't add transition states from a minimum to itself
                continue
            if (u,v) in log_rates:
                log_rates[(u,v)] = log_sum2(log_rates[(u,v)], log_kuv)
                log_rates[(v,u)] = log_sum2(log_rates[(v,u)], log_kvu)
            else:
                log_rates[(u,v)] = log_kuv
                log_rates[(v,u)] = log_kvu
        
        rates = dict(( (uv,np.exp(k)) for uv, k in log_rates.iteritems() ))
        return rates
                
    
    def run(self, mindataf, tsdataf):
        # mindata format
        # energy fvib pgorder I1 I2 I3
        print "reading minima data from file:", mindataf
        mindata = np.genfromtxt(mindataf, usecols=[0,1,2])
        
        # tsdata format
        # energy fvib pgorder min1 min2 I1 I2 I3
        print "reading transition state data from file:", tsdataf
        tsdata = np.genfromtxt(tsdataf, usecols=[0,1,2,3,4])
        
        # subtract 1 so that the indexing starts from 0
        m1_indices = tsdata[:,3].astype(int) - 1
        m2_indices = tsdata[:,4].astype(int) - 1
        
        print "computing rate constants"
        log_k12 = self.compute_rates(mindata, tsdata, m1_indices)
        log_k21 = self.compute_rates(mindata, tsdata, m2_indices)

        max_log_rate = max(log_k12.max(), log_k21.max())
        log_k12 -= max_log_rate
        log_k21 -= max_log_rate
        self.log_rate_subtracted = max_log_rate
        self.rate_norm = np.exp(-max_log_rate)
        
        self.rate_constants = self.make_rates_dict(m1_indices, m2_indices, log_k12, log_k21)
        # add 1 to all the minima id's so that it corresponds to the pathsample indexing
        self.rate_constants = dict(( ((u+1, v+1), rate) for (u,v), rate
                                     in self.rate_constants .iteritems()
                                    ))
        
        print "computing equilibrium occupation probabilities"
        log_Peq = self._log_equilibrium_occupation_probabilities(mindata)
        Peq = np.exp(log_Peq - log_Peq.max())
        # add 1 to all the minima id's so that it corresponds to the pathsample indexing
        self.Peq = dict(( (u+1, P) for u, P in enumerate(Peq) ))
        

def _check_AB(connected_components, A, AB="A"):
    Aclist = [A.intersection(c) for c in connected_components]
    Aclist = filter(lambda c:len(c)>0, Aclist)
    Aconn = set()
    for c in Aclist: Aconn.update(c)
    if Aconn != A:
        print "the following", AB, "nodes are not connected at all"
        print [m for m in A - Aconn]
    if len(Aclist) > 1:
        print "the following groups of", AB, "minima are connected within the group but not between groups"
        for c in Aclist:
            print len(c), "minima:", [m for m in c]

def analyze_graph_error(rates, A, B):
    A = set(A)
    B = set(B)
    
    if A.intersection(B):
        print "the following minima are in both A and B"
        print [m for m in A.intersection(B)]
    
    graph = nx.Graph()
    graph.add_edges_from(rates.iterkeys())
    
    # remove nodes not connected to B
    # TODO: this only works if B is fully connected
    cclist = nx.connected_components(graph)
    cclist = [set(c) for c in cclist]
    
    _check_AB(cclist, A, AB="A")
    _check_AB(cclist, B, AB="B")

def read_minA(fname):
    """load data from min.A or min.B"""
    with open(fname) as fin:
        ids = []
        for i, line in enumerate(fin):
            if i == 0:
                nminima = int(line.split()[0])
            else:
                sline = line.split()
                ids += map(int, sline)
    
    assert nminima == len(ids)
    print len(ids), "minima read from file:", fname
    return ids

def make_rates(directory, T):
    """compute rate constants and equilibrium occupation probabilities from pathsample database"""
    mindata = directory + "/min.data"
    tsdata = directory + "/ts.data"
    generator = RatesFromPathsampleDB(mindata, tsdata, T)
    
    return generator.rate_constants, generator.Peq, generator.rate_norm


description="""Compute rates from a pathsample database.  The transition
states and minima data are read from min.data and ts.data.  The product
and reactant states are read from min.A and min.B.  The rates are computed
by solving a set of linear equations using a sparse solver.
"""

def run(directory, T, A, B, out_prefix, tstart, reverse=False):
    if not reverse:
        source = "A"
        destination = "B"
        direction = "A->B"
    else:
        source = "B"
        destination = "A"
        direction = "B->A"

    rate_constants, Peq, knorm = make_rates(directory, T)
            

    if True:
        fname = "{}.rate_consts".format(out_prefix)
        print "saving rate constants to:", fname
        with open(fname, "w") as fout:
            fout.write("#starting_minimum ending_minimum rate_constant\n")
            for (u,v), k in sorted(rate_constants.iteritems()):
                fout.write("{} {} {}\n".format(u, v, k/knorm))

    print "checking and reducing the graph structure"
    try:
        rate_constants = reduce_rates(rate_constants, B, A=A)
    except Exception:
        analyze_graph_error(rate_constants, A, B)
        raise
    
    print "computing mean first passage times"
    calculator = TwoStateRates(rate_constants, A, B, weights=Peq, check_rates=False)
    calculator.compute_rates(use_umfpack=True)
    print "computing rates"
    kAB = calculator.get_rate_AB()
    print "k({}) {}".format(direction, kAB / knorm)
    
    if True:
        fname = "{}.rates".format(out_prefix)
        print "saving rates and mean first passage times for all minima to reach {} to file {}".format(destination, fname)
        mfpt = sorted([(m, t) for m, t in 
                       calculator.mfpt_computer.mfpt_dict.iteritems()])
        with open(fname, "w") as fout:
            fout.write("#Rates and mean first passage times for each node to reach {}\n".format(destination))
            fout.write("#The rate is just the inverse of the mean first passage time\n")
            fout.write("#minimum_index rate mean_first_passage_time\n")
            for i, t in mfpt:
                mt = t * knorm
                fout.write("{index} {rate} {mfpt}\n".format(index=i, rate=1./mt,
                                                            mfpt=mt))

    print "computing committor probabilities"
    sys.stdout.flush()
    calculator.compute_committors()
    print "computing steady state rate"
    kSS = calculator.get_rate_AB_SS() / knorm
    print "kSS({}) {}".format(direction, kSS)
    
    # print the committors
    # get the alternate definition of committors for the nodes in A and B
    Acomm = calculator.get_alternate_committors(A, B)
    Bcomm = calculator.get_alternate_committors(B, A)
    all_committors = calculator.committor_computer.committor_dict.copy()
    all_committors.update(Acomm)
    all_committors.update(Bcomm)
    
    fname = "{}.committors".format(out_prefix)
    print "saving committor probabilities for all minima to file", fname
    coms = sorted([(m, c) for m, c in all_committors.iteritems()])
    with open(fname, "w") as fout:
        fout.write("#probability a trajectory starting from each node ends up "
                   "in {B} before returning to {A}\n".format(B=destination, A=source))
        fout.write("#minimum_index committor_probability\n")
        for i, c in coms:
            fout.write("{} {}\n".format(i, c))
    
    time_solve = calculator.mfpt_computer.time_solve + calculator.committor_computer.time_solve
    print "time spent solving linear equations", time_solve, "seconds"
    print "total time", time.clock() - tstart


def main():
    """the main loop"""
    tstart =  time.clock()
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument("-d", type=str, default=".",
                        help="directory with the min.data, ts.data files")
    parser.add_argument("-T", type=float, default=1., help="Temperature")
    parser.add_argument("--prefix", type=str, default="out", help="output prefix")
    args = parser.parse_args()
    
    print "temperature", args.T
    directory = args.d
    print "reading from directory:", os.path.abspath(directory)
    out_prefix = args.prefix
    
    A = read_minA(directory+"/min.A")
    B = read_minA(directory+"/min.B")
    
    print "\ncomputing rates from A to B"
    run(directory, args.T, A, B, out_prefix + ".AtoB", tstart, reverse=False)
    print "\ncomputing rates from B to A"
    run(directory, args.T, B, A, out_prefix + ".BtoA", tstart, reverse=True)
    
    
     


if __name__ == "__main__":
    main()
