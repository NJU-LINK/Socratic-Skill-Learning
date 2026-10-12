## Agent3_Idea 1: Named Group Plus External Maintainer

- **Axis choices**: access_policy_topology=primary collaboration via a second named group plus one explicit nonmember user, permission_model=all collaborators need full rwx, inheritance_and_group_propagation=single shared root with standard descendant inheritance
- **What changes**: Keep one shared directory, but replace the seed's two named users with a second collaborating group such as `qa` and one external maintainer user who is not in either `research` or `qa`. Members of both groups and the named maintainer must all be able to create, edit, and traverse shared content, while unrelated accounts remain blocked.
- **Difficulty**: moderate
- **Data source**: Modify the seed Dockerfile to create the extra group and assign users across `research`, `qa`, and one nonmember collaborator. Update tests so content created by a user from one group is editable by a user from the other group and by the named maintainer.
- **Why this tests the skill**: It stays within Linux ACL collaboration, but the solver must combine group ACL entries and named-user ACL entries correctly instead of relying on one group plus symmetric named users.