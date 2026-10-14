<?php

namespace App\Models;

use Illuminate\Foundation\Auth\User as Authenticatable;

class User extends Authenticatable
{
    protected $fillable = ['name', 'email', 'password', 'company_id'];

    public function company()
    {
        return $this->belongsTo(Company::class);
    }
}
