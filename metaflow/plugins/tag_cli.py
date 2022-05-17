import sys

from itertools import chain

from metaflow import namespace
from metaflow.client import Flow, Run
from metaflow.util import resolve_identity
from metaflow.exception import CommandException, MetaflowNotFound
from metaflow.exception import MetaflowNamespaceMismatch

from metaflow._vendor import click


def _print_tags_for_runs_by_groups(
    obj, system_tags_by_group, all_tags_by_group, by_tag
):
    header = [
        "",
        "System tags and *tags*; only *tags* can be modified",
        "--------------------------------------------------------",
        "",
    ]
    obj.echo("\n".join(header), err=False)
    groups = sorted(set(chain(all_tags_by_group.keys(), system_tags_by_group.keys())))
    for group in groups:
        all_tags_in_group = all_tags_by_group.get(group, set())
        system_tags_in_group = system_tags_by_group.get(group, set())
        if by_tag:
            if all_tags_in_group:
                _print_tags_for_group_by_tag(
                    obj, group, all_tags_in_group, is_system=False
                )
            if system_tags_in_group:
                _print_tags_for_group_by_tag(
                    obj, group, system_tags_in_group, is_system=True
                )
        else:
            _print_tags_for_group(
                obj,
                group,
                system_tags_in_group,
                all_tags_in_group,
                skip_per_group_header=(len(all_tags_by_group) == 1),
            )


def _print_tags_for_group(
    obj, group, system_tags, all_tags, skip_per_group_header=False
):
    if not obj.is_quiet:
        # Pretty printing computations
        max_length = max([len(t) for t in all_tags] if all_tags else [0])

        all_tags = sorted(all_tags)
        if sys.version_info[0] < 3:
            all_tags = [
                t if t in system_tags else "*%s*" % t.encode("utf-8") for t in all_tags
            ]
        else:
            all_tags = [t if t in system_tags else "*%s*" % t for t in all_tags]

        num_tags = len(all_tags)

        # We consider 4 spaces in between columns
        # We consider 120 characters as total width
        # We want 120 >= column_count*max_length + (column_count - 1)*4
        column_count = 124 // (max_length + 4)
        if column_count == 0:
            # Make sure we have at least 1 column even for very very long tags
            column_count = 1
            words_per_column = num_tags
        else:
            words_per_column = (num_tags + column_count - 1) // column_count

        # Extend all_tags by empty tags to be able to easily fill up the lines
        addl_tags = words_per_column * column_count - num_tags
        if addl_tags > 0:
            all_tags.extend([" " for _ in range(addl_tags)])

        lines = []
        if not skip_per_group_header:
            lines.append("For run %s" % group)
        for i in range(words_per_column):
            line_values = [
                all_tags[i + j * words_per_column] for j in range(column_count)
            ]
            length_values = [
                max_length + 2 if l[0] == "*" else max_length for l in line_values
            ]
            formatter = "    ".join(["{:<%d}" % l for l in length_values])
            lines.append(formatter.format(*line_values))
        lines.append("")
        obj.echo("\n".join(lines), err=False)
    else:
        # In quiet mode, we display things much more simply, so it is parseable.
        # When displaying by run, we output three columns:
        #  - the comma separated list of runs (usually 1 but more if --all-runs for eg)
        #  - the comma separated list of system tags
        #  - the comma separated list of user tags
        # Columns are separated by a semicolon surrounded by a space on each side
        # to make it visually clear when there are no system tags for example
        obj.echo_always(
            " ; ".join(
                [
                    group,
                    ",".join(sorted(system_tags)),
                    ",".join(sorted(all_tags.difference(system_tags))),
                ]
            )
        )


def _print_tags_for_group_by_tag(obj, group, runs, is_system):
    if not obj.is_quiet:
        # Pretty printing computations
        max_length = max([len(t) for t in runs] if runs else [0])

        all_runs = sorted(runs)

        num_runs = len(all_runs)

        # We consider 4 spaces in between column and we consider 120 characters total
        # width and we want 120 >= column_count*max_length + (column_count - 1)*4
        column_count = 124 // (max_length + 4)
        if column_count == 0:
            # Make sure we have at least 1 column even for very very long tags
            column_count = 1
            words_per_column = num_runs
        else:
            words_per_column = (num_runs + column_count - 1) // column_count

        # Extend all_runs by empty runs to be able to easily fill up the lines
        addl_runs = words_per_column * column_count - num_runs
        if addl_runs > 0:
            all_runs.extend([" " for _ in range(addl_runs)])

        lines = []
        lines.append("For tag %s" % (group if is_system else "*%s*" % group))
        for i in range(words_per_column):
            line_values = [
                all_runs[i + j * words_per_column] for j in range(column_count)
            ]
            length_values = [max_length for l in line_values]
            formatter = "    ".join(["{:<%d}" % l for l in length_values])
            lines.append(formatter.format(*line_values))
        lines.append("")
        obj.echo("\n".join(lines), err=False)
    else:
        # In quiet mode, we display things much more simply so it is parseable.
        # When displaying by tag, we output twp columns:
        #  - the tag (user:<tag> or sys:<tag>)
        #  - the comma separated list of runs
        # Columns are separated by a semicolon surrounded by a space on each side
        # to make it consistent with the by_run listing
        obj.echo_always(
            " ; ".join(
                [
                    "system:%s" % group if is_system else "user:%s" % group,
                    ",".join(runs),
                ]
            )
        )


def _print_tags_for_one_run(obj, run):
    system_tags = {run.pathspec: run.system_tags}
    all_tags = {run.pathspec: run.tags}
    return _print_tags_for_runs_by_groups(obj, system_tags, all_tags, by_tag=False)


def _is_prod_token(token):
    return token and token.startswith("production:")


def _get_client_run_obj(obj, run_id, user_namespace):
    if _is_prod_token(user_namespace):
        raise CommandException(
            "Modifying a scheduled run's tags is currently not allowed."
        )

    flow_name = obj.flow.name

    # handle error messaging for two cases
    # 1. our user tries to tag a new flow before it is run
    # 2. our user makes a typo in --namespace
    try:
        namespace(user_namespace)
        Flow(pathspec=flow_name)
    except MetaflowNotFound:
        raise CommandException(
            "No execution found for *%s*. Please run the flow before tagging."
            % flow_name
        )

    except MetaflowNamespaceMismatch:
        raise CommandException(
            "No execution found for *%s* in namespace *%s*."
            % (flow_name, user_namespace)
        )

    # throw an error with message to include latest run-id when run_id is None
    if run_id is None:
        latest_run_id = Flow(pathspec=flow_name).latest_run.id
        msg = (
            "Please specify a run-id using --run-id.\n"
            "*%s*'s latest execution in namespace *%s* has id *%s*."
            % (flow_name, user_namespace, latest_run_id)
        )
        raise CommandException(msg)
    run_id_parts = run_id.split("/")
    if len(run_id_parts) == 1:
        run_name = "%s/%s" % (flow_name, run_id)
    else:
        raise CommandException("Run-id *%s* is not a valid run-id" % run_id)

    # handle error messaging for three cases
    # 1. our user makes a typo in --run-id
    # 2. our user tries to mutate tags on a meson/production run
    # 3. our user's --run-id does not exist in the default/specified namespace
    try:
        namespace(user_namespace)
        run = Run(pathspec=run_name)
    except MetaflowNotFound:
        raise CommandException("No run *%s* found" % run_name)
    except MetaflowNamespaceMismatch:
        namespace(None)
        run = Run(pathspec=run_name)

        if any([_is_prod_token(tag) for tag in run.system_tags]):
            raise CommandException(
                "Modifying a scheduled run's tags is currently not allowed."
            )

        msg = "Run *%s* does not belong to namespace *%s*\n" % (
            run_name,
            user_namespace,
        )

        user_identifier_tags = [
            tag for tag in run.system_tags if tag.startswith("user:")
        ]
        if user_identifier_tags:
            msg += (
                "You can choose any of the following tags associated with *%s* "
                "to use with option *--namespace*\n" % run_name
            )
            msg += "\n".join(["\t*%s*" % tag for tag in user_identifier_tags])

        raise CommandException(msg)

    return run


@click.group()
def cli():
    pass


@cli.group(help="Commands related to Metaflow tagging.")
def tag():
    pass


@tag.command("add", help="Add tags to a run.")
@click.option(
    "--run-id",
    required=False,  # set False here so we can throw a better error message
    default=None,
    type=str,
    help="Run ID of the specific run to tag. [required]",
)
@click.option(
    "--namespace",
    "user_namespace",
    required=False,
    default=None,
    type=str,
    help="Change namespace from the default (your username) to the one specified.",
)
@click.argument("tags", required=True, type=str, nargs=-1)
@click.pass_obj
def add(obj, run_id, user_namespace, tags):
    user_namespace = resolve_identity() if user_namespace is None else user_namespace
    run = _get_client_run_obj(obj, run_id, user_namespace)

    run.add_tags(tags)

    obj.echo("Operation successful. New tags:", err=False)
    _print_tags_for_one_run(obj, run)


@tag.command("remove", help="Remove tags from a run.")
@click.option(
    "--run-id",
    required=False,  # set False here so we can throw a better error message
    default=None,
    type=str,
    help="Run ID of the specific run to tag. [required]",
)
@click.option(
    "--namespace",
    "user_namespace",
    required=False,
    default=None,
    type=str,
    help="Change namespace from the default (your username) to the one specified.",
)
@click.argument("tags", required=True, type=str, nargs=-1)
@click.pass_obj
def remove(obj, run_id, user_namespace, tags):
    user_namespace = resolve_identity() if user_namespace is None else user_namespace
    run = _get_client_run_obj(obj, run_id, user_namespace)

    run.remove_tags(tags)

    obj.echo("Operation successful. New tags:")
    _print_tags_for_one_run(obj, run)


@tag.command("replace", help="Replace tags of a run.")
@click.option(
    "--run-id",
    required=False,  # set False here, so we can throw a better error message
    default=None,
    type=str,
    help="Run ID of the specific run to tag. [required]",
)
@click.option(
    "--namespace",
    "user_namespace",
    required=False,
    default=None,
    type=str,
    help="Change namespace from the default (your username) to the one specified.",
)
@click.argument("tags", required=True, type=str, nargs=2)
@click.pass_obj
def replace(obj, run_id, user_namespace, tags):
    user_namespace = resolve_identity() if user_namespace is None else user_namespace
    metaflow_run_client = _get_client_run_obj(obj, run_id, user_namespace)

    metaflow_run_client.replace_tag(tags[0], tags[1])

    obj.echo("Operation successful. New tags:")
    _print_tags_for_one_run(obj, metaflow_run_client)


@tag.command("list", help="List tags of a run.")
@click.option(
    "--run-id",
    required=False,
    default=None,
    type=str,
    help="Run ID of the specific run to list.",
)
@click.option(
    "--all",
    "list_all",
    required=False,
    is_flag=True,
    default=False,
    help="List tags across all runs of this flow.",
)
@click.option(
    "--my-runs",
    "my_runs",
    required=False,
    is_flag=True,
    default=False,
    help="List tags across all runs of the flow under the default namespace.",
)
@click.option(
    "--hide-system-tags",
    required=False,
    is_flag=True,
    default=False,
    help="Hide system tags.",
)
@click.option(
    "--by-tag",
    required=False,
    is_flag=True,
    default=False,
    help="Display results by showing runs grouped by tags",
)
@click.option(
    "--by-run",
    required=False,
    is_flag=True,
    default=False,
    help="Display tags grouped by run",
)
@click.argument("arg_run_id", required=False, default=None, type=str)
@click.pass_obj
def tag_list(
    obj, run_id, hide_system_tags, list_all, my_runs, by_tag, by_run, arg_run_id
):
    if run_id is None and arg_run_id is None and not list_all and not my_runs:
        # Assume list_all by default
        list_all = True

    if list_all and my_runs:
        raise CommandException(
            "Option --all cannot be used together with --my-runs.\n"
            "You can run the flow with commands 'tag list --help' "
            "to check the meaning of the two options."
        )

    if run_id is not None and arg_run_id is not None:
        raise CommandException(
            "Specify a run either using --run-id or as an argument but not both"
        )

    if arg_run_id is not None:
        run_id = arg_run_id

    if by_run and by_tag:
        raise CommandException("Option --by-tag cannot be used with --by-run")

    system_tags_by_some_grouping = dict()
    all_tags_by_some_grouping = dict()

    def _populate_tag_groups_from_run(_run):
        if by_run:
            if hide_system_tags:
                all_tags_by_some_grouping[_run.pathspec] = _run.tags - _run.system_tags
            else:
                system_tags_by_some_grouping[_run.pathspec] = _run.system_tags
                all_tags_by_some_grouping[_run.pathspec] = _run.tags
        elif by_tag:
            for t in _run.tags - _run.system_tags:
                all_tags_by_some_grouping.setdefault(t, []).append(_run.pathspec)
            if not hide_system_tags:
                for t in _run.system_tags:
                    system_tags_by_some_grouping.setdefault(t, []).append(_run.pathspec)
        else:
            if hide_system_tags:
                all_tags_by_some_grouping.setdefault("_", set()).update(
                    _run.tags.difference(_run.system_tags)
                )
            else:
                system_tags_by_some_grouping.setdefault("_", set()).update(
                    _run.system_tags
                )
                all_tags_by_some_grouping.setdefault("_", set()).update(_run.tags)

    pathspecs = []
    if list_all or my_runs:
        user_namespace = resolve_identity() if my_runs else None
        namespace(user_namespace)
        for run in Flow(pathspec=obj.flow.name).runs():
            _populate_tag_groups_from_run(run)
            pathspecs.append(run.pathspec)
    else:
        run = _get_client_run_obj(obj, run_id, None)
        _populate_tag_groups_from_run(run)
        pathspecs.append(run.pathspec)

    if not by_run and not by_tag:
        # We list all the runs that match to print them out if needed.
        system_tags_by_some_grouping[
            ",".join(pathspecs)
        ] = system_tags_by_some_grouping["_"]
        all_tags_by_some_grouping[",".join(pathspecs)] = all_tags_by_some_grouping["_"]
        del system_tags_by_some_grouping["_"]
        del all_tags_by_some_grouping["_"]

    _print_tags_for_runs_by_groups(
        obj, system_tags_by_some_grouping, all_tags_by_some_grouping, by_tag
    )
