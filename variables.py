import numpy as np
import pandas as pd
from urbansim.utils import misc
import orca
import datasources
from urbansim_defaults import utils
from urbansim_defaults import variables


#####################
# HOUSEHOLDS VARIABLES
#####################


@orca.column('households', 'ones', cache=True)
def income_decile(households):
    return pd.Series(1, households.index)


@orca.column('households', 'tmnode_id', cache=True)
def node_id(households, buildings):
    return misc.reindex(buildings.tmnode_id, households.building_id)


#####################
# HOMESALES VARIABLES
#####################


@orca.column('homesales', 'juris_ave_income', cache=True)
def juris_ave_income(parcels, homesales):
    return misc.reindex(parcels.juris_ave_income, homesales.parcel_id)


@orca.column('homesales', 'is_sanfran', cache=True)
def is_sanfran(parcels, homesales):
    return misc.reindex(parcels.is_sanfran, homesales.parcel_id)


#####################
# COSTAR VARIABLES
#####################


@orca.column('costar', 'juris_ave_income', cache=True)
def juris_ave_income(parcels, costar):
    return misc.reindex(parcels.juris_ave_income, costar.parcel_id)


@orca.column('costar', 'is_sanfran', cache=True)
def is_sanfran(parcels, costar):
    return misc.reindex(parcels.is_sanfran, costar.parcel_id)


@orca.column('costar', 'general_type')
def general_type(costar):
    return costar.PropertyType


@orca.column('costar', 'node_id')
def node_id(parcels, costar):
    return misc.reindex(parcels.node_id, costar.parcel_id)


@orca.column('costar', 'tmnode_id')
def tmnode_id(parcels, costar):
    return misc.reindex(parcels.tmnode_id, costar.parcel_id)


@orca.column('costar', 'zone_id')
def zone_id(parcels, costar):
    return misc.reindex(parcels.zone_id, costar.parcel_id)


#####################
# JOBS VARIABLES
#####################


@orca.column('jobs', 'tmnode_id', cache=True)
def tmnode_id(jobs, buildings):
    return misc.reindex(buildings.tmnode_id, jobs.building_id)


@orca.column('jobs', 'naics', cache=True)
def naics(jobs):
    return jobs.sector_id


@orca.column('jobs', 'empsix', cache=True)
def empsix(jobs, settings):
    return jobs.naics.map(settings['naics_to_empsix'])


@orca.column('jobs', 'empsix_id', cache=True)
def empsix_id(jobs, settings):
    return jobs.empsix.map(settings['empsix_name_to_id'])


@orca.column('jobs', 'preferred_general_type')
def preferred_general_type(jobs, buildings, settings):
    # this column is the preferred general type for this job - this is used
    # in the non-res developer to determine how much of a building type to
    #  use.  basically each job has a certain pdf by sector of the building
    # types is prefers and so we give each job a preferred type based on that
    # pdf.  note that if a job is assigned a building, the building's type is
    # it's preferred type by definition

    s = misc.reindex(buildings.general_type, jobs.building_id)

    sector_pdfs = pd.DataFrame(settings['job_sector_to_type'])
    # normalize (to be safe)
    sector_pdfs = sector_pdfs / sector_pdfs.sum()

    for sector in sector_pdfs.columns:
        mask = ((s == "Other") & (jobs.empsix == sector))

        sector_pdf = sector_pdfs[sector]
        s[mask] = np.random.choice(sector_pdf.index,
                                   size=mask.value_counts()[True],
                                   p=sector_pdf.values)

    return s


#####################
# BUILDINGS VARIABLES
#####################


@orca.column('buildings', 'tmnode_id', cache=True)
def tmnode_id(buildings, parcels):
    return misc.reindex(parcels.tmnode_id, buildings.parcel_id)


@orca.column('buildings', 'juris_ave_income', cache=True)
def juris_ave_income(parcels, buildings):
    return misc.reindex(parcels.juris_ave_income, buildings.parcel_id)


@orca.column('buildings', 'is_sanfran', cache=True)
def is_sanfran(parcels, buildings):
    return misc.reindex(parcels.is_sanfran, buildings.parcel_id)


@orca.column('buildings', 'sqft_per_unit', cache=True)
def unit_sqft(buildings):
    return (buildings.building_sqft /
            buildings.residential_units.replace(0, 1)).clip(400, 6000)


@orca.column('buildings', cache=True)
def modern_condo(buildings):
    # this is to try and differentiate between new construction
    # in the city vs in the burbs
    return ((buildings.year_built > 2000) * (buildings.building_type_id == 3))\
        .astype('int')


#####################
# PARCELS VARIABLES
#####################

# these are actually functions that take parameters, but are parcel-related
# so are defined here
@orca.injectable('parcel_average_price', autocall=False)
def parcel_average_price(use, quantile=.5):
    # I'm testing out a zone aggregation rather than a network aggregation
    # because I want to be able to determine the quantile of the distribution
    # I also want more spreading in the development and not keep it localized
    if use == "residential":
        buildings = orca.get_table('buildings')
        # get price per sqft
        s = buildings.residential_price / buildings.sqft_per_unit
        # limit to res
        s = s[buildings.general_type == "Residential"]
        # group by zoneid and get 80th percentile
        s = s.groupby(buildings.zone_id).quantile(.8).clip(150, 1250)
        # broadcast back to parcel's index
        s = misc.reindex(s, orca.get_table('parcels').zone_id)
        # shifters
        cost_shifters = orca.get_table("parcels").cost_shifters
        price_shifters = orca.get_table("parcels").price_shifters
        return s / cost_shifters * price_shifters

    if 'nodes' not in orca.list_tables():
        return pd.Series(0, orca.get_table('parcels').index)

    return misc.reindex(orca.get_table('nodes')[use],
                        orca.get_table('parcels').node_id)


@orca.injectable('parcel_sales_price_sqft_func', autocall=False)
def parcel_sales_price_sqft(use):
    s = parcel_average_price(use)
    if use == "residential":
        s *= 1.0
    return s


@orca.injectable('parcel_is_allowed_func', autocall=False)
def parcel_is_allowed(form):
    settings = orca.get_injectable('settings')
    form_to_btype = settings["form_to_btype"]
    # we have zoning by building type but want
    # to know if specific forms are allowed
    allowed = [orca.get_table('zoning_baseline')
               ['type%d' % typ] > 0 for typ in form_to_btype[form]]
    s = pd.concat(allowed, axis=1).max(axis=1).\
        reindex(orca.get_table('parcels').index).fillna(False)

    return s


@orca.column('parcels', 'juris_ave_income', cache=True)
def juris_ave_income(households, buildings, parcels_geography, parcels):
    h = orca.merge_tables("households",
                          [households, buildings, parcels_geography],
                          columns=["jurisdiction", "income"])
    s = h.groupby(h.jurisdiction).income.quantile(.5)
    return misc.reindex(s, parcels_geography.jurisdiction).\
        reindex(parcels.index).fillna(s.median())


@orca.column('parcels', 'oldest_building_age')
def oldest_building_age(parcels, year):
    return year - parcels.oldest_building


@orca.column('parcels', 'is_sanfran', cache=True)
def is_sanfran(parcels_geography, buildings, parcels):
    return (parcels_geography.juris_name == "San Francisco").\
        reindex(parcels.index).fillna(False).astype('int')


# actual columns start here
@orca.column('parcels', 'max_far', cache=True)
def max_far(parcels, scenario, scenario_inputs):
    s = utils.conditional_upzone(scenario, scenario_inputs,
                                 "max_far", "far_up").\
        reindex(parcels.index)
    return s * ~parcels.nodev


# returns a vector where parcels are ALLOWED to be built
@orca.column('parcels')
def parcel_rules(parcels):
    # removes parcels with buildings < 1940,
    # and single family homes on less then half an acre
    s = (parcels.oldest_building < 1940) | \
        ((parcels.total_residential_units == 1) & (parcels.parcel_acres < .5))
    s = (~s.reindex(parcels.index).fillna(False)).astype('int')
    return s

GROSS_AVE_UNIT_SIZE = 1000


@orca.column('parcels', 'zoned_du', cache=True)
def zoned_du(parcels):
    s = parcels.max_dua * parcels.parcel_acres
    s2 = parcels.max_far * parcels.parcel_size / GROSS_AVE_UNIT_SIZE
    s3 = parcel_is_allowed('residential')
    return (s.fillna(s2)*s3).reindex(parcels.index).fillna(0).astype('int')


@orca.column('parcels', 'total_non_residential_sqft', cache=True)
def total_non_residential_sqft(parcels, buildings):
    return buildings.non_residential_sqft.groupby(buildings.parcel_id).sum().\
        reindex(parcels.index).fillna(0)


@orca.column('parcels', 'zoned_du_underbuild')
def zoned_du_underbuild(parcels):
    # subtract from zoned du, the total res units, but also the equivalent
    # of non-res sqft in res units
    s = (parcels.zoned_du - parcels.total_residential_units -
         parcels.total_non_residential_sqft / GROSS_AVE_UNIT_SIZE)\
         .clip(lower=0)
    ratio = (s / parcels.total_residential_units).replace(np.inf, 1)
    # if the ratio of additional units to existing units is not at least .5
    # we don't build it - I mean we're not turning a 10 story building into an
    # 11 story building
    s = s[ratio > .5].reindex(parcels.index).fillna(0)
    return s.astype('int')


@orca.column('parcels')
def zoned_du_underbuild_nodev(parcels):
    return (parcels.zoned_du_underbuild * parcels.parcel_rules).astype('int')


@orca.column('parcels')
def nodev(zoning_baseline, parcels):
    return zoning_baseline.nodev.reindex(parcels.index).\
        fillna(0).astype('bool')


@orca.column('parcels', 'max_dua', cache=True)
def max_dua(parcels, scenario, scenario_inputs):
    s = utils.conditional_upzone(scenario, scenario_inputs,
                                 "max_dua", "dua_up").\
        reindex(parcels.index)
    return s * ~parcels.nodev


@orca.column('parcels', 'max_height', cache=True)
def max_height(parcels, zoning_baseline):
    return zoning_baseline.max_height.reindex(parcels.index)


@orca.column('parcels', 'residential_purchase_price_sqft')
def residential_purchase_price_sqft(parcels):
    return parcels.building_purchase_price_sqft


@orca.column('parcels', 'residential_sales_price_sqft')
def residential_sales_price_sqft(parcel_sales_price_sqft_func):
    return parcel_sales_price_sqft_func("residential")


# for debugging reasons this is split out into its own function
@orca.column('parcels', 'building_purchase_price_sqft')
def building_purchase_price_sqft():
    return parcel_average_price("residential")


@orca.column('parcels', 'building_purchase_price')
def building_purchase_price(parcels):
    return (parcels.total_sqft * parcels.building_purchase_price_sqft).\
        reindex(parcels.index).fillna(0)


@orca.column('parcels', 'land_cost')
def land_cost(parcels):
    return parcels.building_purchase_price + parcels.parcel_size * 12.21


@orca.column('parcels', 'county')
def county(parcels, settings):
    return parcels.county_id.map(settings["county_id_map"])


@orca.column('parcels', 'cost_shifters')
def cost_shifters(parcels, settings):
    return parcels.county.map(settings["cost_shifters"])


@orca.column('parcels', 'price_shifters')
def price_shifters(parcels, settings):
    return parcels.pda.map(settings["pda_price_shifters"]).fillna(1.0)


@orca.column('parcels', 'node_id', cache=True)
def node_id(parcels, net):
    s = net["walk"].get_node_ids(parcels.x, parcels.y)
    fill_val = s.value_counts().index[0]
    s = s.reindex(parcels.index).fillna(fill_val).astype('int')
    return s


@orca.column('parcels', 'tmnode_id', cache=True)
def node_id(parcels, net):
    s = net["drive"].get_node_ids(parcels.x, parcels.y)
    fill_val = s.value_counts().index[0]
    s = s.reindex(parcels.index).fillna(fill_val).astype('int')
    return s
