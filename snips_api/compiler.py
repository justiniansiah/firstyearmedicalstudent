"""
Compiler used by components.Snippet.generate_chain_sql()
"""

from .exceptions import *
from db_tools import AppDBConnection, AppCursor

from itertools import zip_longest


def snippet_chain_to_sql_data(snip, insert_method='timid'):
    """Creates SQL for all snippets reachable from the given 'root snippet'

    Returns a list of (query, data) tuples.
    """
    try:
        int(snip.snip_id)
    except ValueError:
        raise CompilerError('The starting snippet has invalid snip_id '
                            '(expected int, got {})'.format(str(snip.snip_id))
                           )

    # Collate unique snippets starting with the root
    # get_snippets_network() returns list of unique snippets connected to the
    # 'root' node, including the root node itself
    snips = snip.get_snippets_tree()

    
    # Assign snip_ids to snippets
    # Snippets with valid int(snippet.snip_id) will use that snip_id
    # Snippets with pending snip_id will be assigned an unused on in the db
    dict_snip_to_id, ids_to_drop = assign_ids(snips, insert_method)

    drop_query = """DELETE FROM snippets WHERE snip_id in ({})""".format(
        make_placeholders_for(ids_to_drop))

    # output is a list of (query, data) tuples
    output = []
    if ids_to_drop:
        output.append((drop_query, ids_to_drop))
    output.append(generate_sql_for_snippets(snips, dict_snip_to_id))
    for query, data in generate_sql_for_choices(snips, dict_snip_to_id):
        output.append((query, data))

    return output


def assign_ids(snips, insert_method):
    """Matches snippets with spare snip_ids and identifies snip_ids to drop"""
    # Complain if first snippet has no snip_id to count up from
    try:
        root_id = int(snips[0].snip_id)
    except TypeError:
        raise CompilerError('first snippet in snippet stack has invalid '
                            'snip_id (expected int, got {})'
                           ).format(repr(snips[0].snip_id))

    # Complain if you don't insert it properly
    accept_methods = ['timid', 'rough']
    if insert_method not in accept_methods:
        raise CompilerError('unexpected insert_method option '
                            '(insertion must be "timid" or "rough", not "{}")'
                           ).format(insert_method)

    # Split the snips into 2 lists
    pending_snip_id = []   # snippets that snip.snip_id == 'pending'
    declared_snip_id = []  # snippets that snip.snip_id != 'pending'
    for snip in snips:
        if snip.snip_id != 'pending':
            declared_snip_id.append(snip)
        else:
            pending_snip_id.append(snip)
    
    drop_snip_ids = []
    # Fetch rows that contain snip_ids in declared_snip_id
    for row in fetch_rows_with_snipids(
        [snippet.snip_id for snippet in declared_snip_id]
    ).values():
        if row:
            exiting_snip_id = row['snip_id']
            # Complain if encountering resistance when timidly inserting
            if insert_method == 'timid':
                raise TimidError(exiting_snip_id)
            elif insert_method == 'rough':
                drop_snip_ids.append(exiting_snip_id)

    # If using rough insert, it doesn't matter if rows already exist among
    # the declared snip_ids, because we will overwrite those rows.
    # If we made it this far, just map all the snippets to a snip_id
    # (by finding spare snip_ids and using the declared snip_ids)

    # Find spare snip_ids for the snippets who are pending one
    spare_ids = find_spare_snipids(startfrom=root_id+1, 
                                   needed=len(pending_snip_id))

    # Map the snippets to the snip_ids they will adopt
    output = dict()
    for snippet, snip_id in zip(pending_snip_id, spare_ids):
        output[snippet] = snip_id
    for snippet in declared_snip_id:
        output[snippet] = snippet.snip_id

    # SAN check
    assert(len(snips) == len(output))
    return output, drop_snip_ids


def fetch_rows_with_snipids(list_snip_ids):
    """Checks for each snip_id in `list_snip_ids` if a record exists already

    Returns a dict of {snip_id: (row or None)}
    """
    output = {snip_id: None for snip_id in list_snip_ids}
    
    query = """SELECT * FROM snippets WHERE snip_id IN ({})""".format(
        make_placeholders_for(list_snip_ids))
    with AppCursor() as cur:
        cur.execute(query, list_snip_ids)
        rows = cur.fetchall()
    
    existing_rows = {row['snip_id']: row for row in rows}
    output.update(existing_rows)
    return output


def find_spare_snipids(startfrom, needed):
    """Provides list containing snip_ids that are unused in the db"""
    free_ids = []
    found = 0
    while found < needed:
        # Each loop defines a list of 100 candidate snip_ids
        candidate_snipids = list(range(startfrom, startfrom+100))

        # fetch_rows_with_snipids() returns a dict of {row['snip_id']: row}
        # Fetch rows that contain any of our candidates
        existing_snip_ids = [
            snip_id for snip_id, row in 
            fetch_rows_with_snipids(candidate_snipids).items()
            if row is not None
        ]

        # If none of the candidates exist in the db:
        if not existing_snip_ids:
            # Transfer as many snip_ids from candidate_snipids as we need/can
            for candidate in candidate_snipids:
                if found < needed:
                    free_ids.append(candidate)
                    found += 1
                else:
                    break
        
        # But if some candidates are already used in the db:
        else:
            # Remove existing snip_ids from candidate_snipids
            for i in existing_snip_ids:
                candidate_snipids.remove(i)

            # Transfer as many snip_ids from candidate_snipids as we need/can
            for candidate in candidate_snipids:
                if found < needed:
                    free_ids.append(candidate)
                    found += 1
                else:
                    break
        # For next loop in `while`, start from the next 100 candidates
        startfrom += 100
    
    # Once we're done finding candidates, do a SAN check
    assert(len(free_ids) == needed)
    return free_ids


def generate_sql_for_snippets(snips, dict_snip_to_id):
    """Compiles query and data for inserting into snippets table

    Returns a single tuple of (sql, values). `values` is a list of values
    that are data to bind to the returned query.
    """
    # `placeholders` is a list of n copies of '(%s, %s)' where n = len(snips)
    # They are placeholders for actual values that are merged into the query
    # when the query is executed to the database via psycopg2
    sql = """INSERT INTO snippets(snip_id, game_text) VALUES {}""".format(
        make_placeholders_for(snips, using='(%s, %s)'))
    
    # `values` is a flat (non-nested) list of values to merge into sql
    values = []
    for snippet, snip_id in dict_snip_to_id.items():
        values.append(snippet.text)
        values.append(snip_id)
    
    return (sql, values)


def generate_sql_for_choices(snips, dict_snip_to_id):
    """Compiles query and data for inserting into choices table

    Returns a list of (sql, data) tuples. The `data` in each tuple is a list
    of values that are data to bind to the returned query.
    """
    # choices_data is a list of dictionaries
    # dict key is column name and dict value is the insert value
    choices_data = []
    for snip in snips:
        for choice in snip.choices:
            choices_data.append(
                extract_col_data_from_choice(choice, dict_snip_to_id)
            )
            
    output = []
    for choice_dict in choices_data:
        # `cols` is a string containing table columns to insert to
        cols = ', '.join(choice_dict.keys())
        sql = """INSERT INTO choices({}) VALUES ({})""".format(
            cols, make_placeholders_for(choice_dict.keys()))
        
        data = list(choice_dict.values())
        output.append((sql, data))

    return output


def make_placeholders_for(iterable, using='%s'):
    return ', '.join([using] * len(iterable))


def extract_col_data_from_choice(choice, dict_snip_to_id):
    """Translates choice attributes into table fields

    Resolves attributes into appropriate datatypes e.g. snip -> snip.snip_id
    
    Returns:
        {col_name: attrib}
    """
    col_mod_flg = 'mod_flg_{num}'
    max_num_cols_mod_flg = 3

    col_check_flg = 'check_flg_{num}'
    max_num_cols_check_flg = 3

    output = {}
    output['choice_label'] = str(choice.label)
    output['snip_id'] = int(dict_snip_to_id[choice.snippet])
    output['next_snip_id'] = int(dict_snip_to_id[choice.next_snippet])
    
    modifies = choice.modifies_flags.copy()
    conditions = choice.check_flags.copy()

    for expression_list, col_name, max_num_cols in [
        [modifies,   col_mod_flg,   max_num_cols_mod_flg], 
        [conditions, col_check_flg, max_num_cols_check_flg]
    ]:
        if len(expression_list) > max_num_cols:
            raise CompilerError('Trying to insert too many flags to check or '
                                'modify (expected {}, got {})'.format(
                                    len(num_of_cols), 
                                    len(expression_list)
                                ))
        for i, expr in zip_longest(
            range(max_num_cols), 
            expression_list[:max_num_cols], 
            fillvalue=None
        ):
            column = col_name.format(num=i+1)
            output[column] = expr
    return output

