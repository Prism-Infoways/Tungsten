<?php

namespace App\Models;

use Illuminate\Foundation\Auth\User as Authenticatable;

class User extends Authenticatable
{
    protected function casts(): array
    {
        return ['is_admin' => 'boolean', 'password' => 'hashed'];
    }

    public function posts()
    {
        return $this->hasMany(Post::class, 'author_id');
    }
}
