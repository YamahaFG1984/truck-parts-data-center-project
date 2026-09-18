def cost_visibility(request):
    """Whether cost prices may be shown.

    Every signed-in user for the MVP; templates already check this flag so hiding
    costs from sales later is a one-line change here (PRD open question).
    """
    user = getattr(request, "user", None)
    return {"can_view_cost": bool(user and user.is_authenticated)}
