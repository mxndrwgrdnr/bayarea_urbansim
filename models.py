from urbansim.developer import sqftproforma, developer
from urbansim.utils import networks
import urbansim.models.yamlmodelrunner as ymr
from dataset import *
import time


def _buildings_df(dset, filter=None):
    bdf = dset.view("buildings").build_df()
    if filter is not None:
        bdf.query(filter)
    return dset.merge_nodes(bdf.fillna(0))


def _households_df(dset):
    return dset.view("households").build_df()


def _jobs_df(dset):
    return dset.view("jobs").build_df()


def _homesales_df(dset):
    return dset.merge_nodes(dset.view("homesales").build_df())


def _apartments_df(dset):
    return dset.merge_nodes(dset.view("apartments").build_df())


def _costar_df(dset):
    return dset.merge_nodes(dset.view("costar").build_df())


def clear_cache(dset):
    dset.clear_views()


def cache_variables(dset):
    _buildings_df(dset)
    _households_df(dset)
    _jobs_df(dset)
    _homesales_df(dset)
    _apartments_df(dset)
    _costar_df(dset)


# residential sales hedonic
def rsh_estimate(dset):
    return ymr.hedonic_estimate(_homesales_df(dset), "rsh.yaml")


def rsh_simulate(dset):
    return ymr.hedonic_simulate(_buildings_df(dset), "rsh.yaml",
                                dset.buildings, "residential_sales_price")


# residential rent hedonic
def rrh_estimate(dset):
    return ymr.hedonic_estimate(_apartments_df(dset), "rrh.yaml")


def rrh_simulate(dset):
    return ymr.hedonic_simulate(_buildings_df(dset), "rrh.yaml",
                                dset.buildings, "residential_rent")


# non-residential hedonic
def nrh_estimate(dset):
    return ymr.hedonic_estimate(_costar_df(dset), "nrh.yaml")


def nrh_simulate(dset):
    return ymr.hedonic_simulate(_buildings_df(dset), "nrh.yaml",
                                dset.buildings, "non_residential_rent")


# household location choice
def _hlcm_estimate(dset, cfgname):
    return ymr.lcm_estimate(_households_df(dset),
                            "building_id",
                            _buildings_df(dset,
                                          filter="general_type == 'Residential'"),
                            cfgname)


def _hlcm_simulate(dset, cfgname):
    units = ymr.get_vacant_units(_households_df(dset),
                                 "building_id",
                                 _buildings_df(dset,
                                               filter="general_type == 'Residential'"),
                                 "residential_units")
    return ymr.lcm_simulate(_households_df(dset), units, cfgname, dset.households, "building_id")


# household location choice owner
def hlcmo_estimate(dset):
    return _hlcm_estimate(dset, "hlcmo.yaml")


def hlcmo_simulate(dset):
    return _hlcm_simulate(dset, "hlcmo.yaml")


# household location choice renter
def hlcmr_estimate(dset):
    return _hlcm_estimate(dset, "hlcmr.yaml")


def hlcmr_simulate(dset):
    return _hlcm_simulate(dset, "hlcmr.yaml")


# employment location choice
def elcm_estimate(dset):
    return ymr.lcm_estimate(_jobs_df(dset),
                            "building_id",
                            _buildings_df(dset,
                                          filter="general_type != 'Residential'"),
                            "elcm.yaml")


def elcm_simulate(dset):
    units = ymr.get_vacant_units(_jobs_df(dset),
                                 "building_id",
                                 _buildings_df(dset,
                                               filter="general_type != 'Residential'"),
                                 "non_residential_units")
    return ymr.lcm_simulate(_jobs_df(dset), units, "elcm.yaml", dset.jobs, "building_id")


def households_relocation(dset):
    return ymr.simple_relocation(dset.households, .05)


def jobs_relocation(dset):
    return ymr.simple_relocation(dset.jobs, .08)


def households_transition(dset):
    return ymr.simple_transition(dset, "households", .05)


def jobs_transition(dset):
    return ymr.simple_transition(dset, "jobs", .05)


def build_networks(dset):
    if dset.NETWORKS is None:
        dset.NETWORKS = networks.Networks(
            [os.path.join(misc.data_dir(), x) for x in ['osm_bayarea.jar']],
            factors=[1.0],
            maxdistances=[2000],
            twoway=[1],
            impedances=None)

    #parcels = networks.NETWORKS.addnodeid(dset.parcels)
    #dset.save_tmptbl("parcels", parcels)


def neighborhood_vars(dset):
    nodes = networks.from_yaml(dset, "networks.yaml")
    dset.save_tmptbl("nodes", nodes)


def price_vars(dset):
    nodes = networks.from_yaml(dset, "networks2.yaml")
    dset.save_tmptbl("nodes_prices", nodes)


def feasibility(dset):
    pf = sqftproforma.SqFtProForma()

    parcels = dset.view("parcels")
    df = parcels.build_df()

    # add prices for each use
    for use in pf.config.uses:
        df[use] = parcels.price(use)

    # convert from cost to yearly rent
    df["residential"] *= pf.config.cap_rate
    print df[pf.config.uses].describe()

    d = {}
    for form in pf.config.forms:
        print "Computing feasibility for form %s" % form
        d[form] = pf.lookup(form, df[parcels.allowed(form)])

    far_predictions = pd.concat(d.values(), keys=d.keys(), axis=1)

    dset.save_tmptbl("feasibility", far_predictions)


def residential_developer(dset):
    residential_target_vacancy = .15
    dev = developer.Developer(dset.feasibility)

    target_units = dev.compute_units_to_build(len(dset.households),
                                              dset.buildings.residential_units.sum(),
                                              residential_target_vacancy)

    parcels = dset.view("parcels")
    new_buildings = dev.pick("residential",
                             target_units,
                             parcels.parcel_size,
                             parcels.ave_unit_sqft,
                             parcels.total_units,
                             max_parcel_size=200000,
                             drop_after_build=True)

    new_buildings["year_built"] = dset.year
    new_buildings["form"] = "residential"
    new_buildings["building_type_id"] = new_buildings["form"].apply(dset.random_type)
    new_buildings["stories"] = new_buildings.stories.apply(np.ceil)
    for col in ["residential_sales_price", "residential_rent", "non_residential_rent"]:
        new_buildings[col] = np.nan

    #print "NEW BUILDINGS"
    #print new_buildings[dset.buildings.columns].describe()

    print "Adding {} buildings with {:,} residential units".format(len(new_buildings),
                                                                   new_buildings.residential_units.sum())

    all_buildings = dev.merge(dset.buildings, new_buildings[dset.buildings.columns])
    dset.save_tmptbl("buildings", all_buildings)


def non_residential_developer(dset):
    non_residential_target_vacancy = .15
    dev = developer.Developer(dset.feasibility)

    target_units = dev.compute_units_to_build(len(dset.jobs),
                                              dset.view("buildings").non_residential_units.sum(),
                                              non_residential_target_vacancy)

    parcels = dset.view("parcels")
    new_buildings = dev.pick(["office", "retail", "industrial"],
                             target_units,
                             parcels.parcel_size,
                             # This is hard-coding 500 as the average sqft per job
                             # which isn't right but it doesn't affect outcomes much
                             # developer will build enough units assuming 500 sqft
                             # per job but then it just returns the result as square
                             # footage and the actual building_sqft_per_job will be
                             # used to compute non_residential_units.  In other words,
                             # we can over- or under- build the number of units here
                             # but we should still get roughly the right amount of
                             # development out of this and the final numbers are precise.
                             # just move this up and down if dev is over- or under-
                             # buildings things
                             pd.Series(500, index=parcels.index),
                             dset.view("parcels").total_nonres_units,
                             max_parcel_size=200000,
                             drop_after_build=True,
                             residential=False)

    new_buildings["year_built"] = dset.year
    new_buildings["building_type_id"] = new_buildings["form"].apply(dset.random_type)
    new_buildings["residential_units"] = 0
    new_buildings["stories"] = new_buildings.stories.apply(np.ceil)
    for col in ["residential_sales_price", "residential_rent", "non_residential_rent"]:
        new_buildings[col] = np.nan

    #print "NEW BUILDINGS"
    #print new_buildings[dset.buildings.columns].describe()

    print "Adding {} buildings with {:,} non-residential sqft".format(len(new_buildings),
                                                                      new_buildings.non_residential_sqft.sum())

    all_buildings = dev.merge(dset.buildings, new_buildings[dset.buildings.columns])
    dset.save_tmptbl("buildings", all_buildings)


def _run_models(dset, model_list, years):

    for year in years:

        dset.year = year

        t1 = time.time()

        for model in model_list:
            t2 = time.time()
            print "\n" + model + "\n"
            globals()[model](dset)
            print "Model %s executed in %.3fs" % (model, time.time()-t2)
        print "Year %d completed in %.3fs" % (year, time.time()-t1)